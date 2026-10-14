# SPDX-License-Identifier: AGPL-3.0-or-later
"""A person connecting their own Paystack Index account from a card (docs/commerce.md, "Connecting").

The person signs in at Index (OAuth authorization code with PKCE; 234 registered itself as a client once for
the deployment). The card holds a link to Index with a `state` that only this attempt knows; Index sends the
browser back to the chat host, which hands the code and the state to `complete` as the signed-in person. The
state is taken once, for that person's attempt, while it is open (attempts.py), and the code is exchanged
here, so a token never passes through a browser, a card or a model. Chowdeck is then linked from the same card
(linking.py). Disconnecting forgets the tokens here and asks Index to revoke them where it offers that."""

from contextlib import suppress

from ...audit import Audit
from ...clock import Clock
from ...errors import DomainError
from .attempts import Attempt, Attempts
from .catalog import Entry, IndexCatalog
from .connection_view import needs_linking, view_of
from .linking import Linking
from .naming import index_id_of
from .oauth import IndexOAuth, challenge_of
from .registrations import Registrations
from .store import Connection, IndexStore
from .wire import IndexProblem

CALLBACK_PATH = "/connect/index/callback"
STATE_UNKNOWN = DomainError(
    "INDEX_STATE",
    "This sign-in is not one 234 is waiting for: it was already used, it belongs to someone else, or it ran "
    "out. Start again from the card in the chat.",
)
NOT_YOURS = DomainError("CARD_NOT_FOUND", "This connection card is not yours or no longer exists.")
UNAVAILABLE = DomainError("INDEX_UNAVAILABLE", "Paystack Index did not answer. Try again in a moment.")


class IndexAccounts:
    def __init__(
        self,
        store: IndexStore,
        attempts: Attempts,
        oauth: IndexOAuth,
        catalog: IndexCatalog,
        linking: Linking,
        registrations: Registrations,
        redirect_uri: str,
        clock: Clock,
        audit: Audit,
    ) -> None:
        self._store, self._attempts, self._oauth, self._catalog = store, attempts, oauth, catalog
        self._linking, self._registrations, self._redirect = linking, registrations, redirect_uri
        self._clock, self._audit = clock, audit

    async def _attempt(self, owner: str, card_id: str) -> Attempt:
        found = await self._attempts.get(owner, card_id)
        if found is None:
            raise NOT_YOURS
        return found

    async def _entry(self, attempt: Attempt, reader: str | None = None) -> Entry | None:
        index_id = index_id_of(attempt.merchant_id or "")
        return await self._catalog.entry(index_id, reader) if index_id else None

    async def _view(
        self, owner: str, card_id: str, link: str | None = None, notice: str | None = None
    ) -> dict:
        attempt = await self._attempt(owner, card_id)
        connection = await self._store.connection(owner)
        entry = await self._entry(attempt, owner if connection else None)
        return view_of(attempt, connection, entry, self._clock.now(), link, notice)

    async def status(self, owner: str, card_id: str) -> dict:
        return await self._view(owner, card_id)

    async def begin(self, owner: str, merchant_id: str | None) -> dict:
        """A card for connecting, at the step the person is at: signing in at Index if they have not, linking
        the merchant if it needs that, or already connected."""
        attempt = await self._attempts.start(owner, merchant_id)
        connection = await self._store.connection(owner)
        if connection is None:
            return await self.restart(owner, attempt.id)
        step = "phone" if needs_linking(await self._entry(attempt, owner), connection) else "done"
        await self._attempts.advance(owner, attempt.id, step)
        return await self._view(owner, attempt.id)

    async def restart(self, owner: str, card_id: str) -> dict:
        """The sign-in link of a card, with a new state and a fresh ten minutes."""
        await self._attempt(owner, card_id)
        armed = await self._attempts.arm(owner, card_id)
        if armed is None:
            raise NOT_YOURS
        try:
            registration = await self._registrations.current()
            link = await self._oauth.authorize_url(
                registration, self._redirect, armed.state, challenge_of(armed.verifier)
            )
        except IndexProblem as problem:
            raise UNAVAILABLE from problem
        return await self._view(owner, card_id, link=link)

    async def complete(self, owner: str, code: str, state: str) -> dict:
        """The sign-in came back: exchange the code for this person's tokens and keep them sealed."""
        taken = await self._attempts.take(owner, state)
        if taken is None:
            self._audit.log("index.callback_refused")
            raise STATE_UNKNOWN
        attempt, verifier = taken
        try:
            registration = await self._registrations.current()
            tokens = await self._oauth.exchange(registration, self._redirect, code, verifier)
        except IndexProblem as problem:
            await self._attempts.mark(owner, attempt.id, "expired")
            self._audit.log("index.exchange_failed", attempt=attempt.id)
            raise DomainError(
                "INDEX_SIGN_IN_FAILED", "Paystack Index did not accept the sign-in. Try again from the card."
            ) from problem
        await self._store.keep(owner, tokens, registration.client_id)
        connection = await self._store.connection(owner)
        entry = await self._entry(attempt, owner)
        step = "phone" if connection and needs_linking(entry, connection) else "done"
        await self._attempts.advance(owner, attempt.id, step)
        self._audit.log("index.connected", attempt=attempt.id)
        return await self._view(owner, attempt.id)

    async def denied(self, owner: str, state: str) -> None:
        """Index sent the person back without a code: they said no."""
        taken = await self._attempts.take(owner, state)
        if taken is not None:
            await self._attempts.mark(owner, taken[0].id, "denied")

    async def _to_link(self, owner: str, attempt: Attempt) -> str:
        """The Index merchant a card links with a phone and a code, when it is for one that needs that."""
        entry = await self._entry(attempt, owner)
        if entry is None or not entry.asks_link:
            raise DomainError("INVALID_INPUT", "This card is not connecting a merchant that needs a code.")
        return entry.index_id

    async def send_code(self, owner: str, card_id: str, phone: str) -> dict:
        attempt = await self._attempt(owner, card_id)
        await self._linking.send_code(owner, attempt, await self._to_link(owner, attempt), phone)
        return await self._view(owner, card_id)

    async def confirm_code(self, owner: str, card_id: str, phone: str, code: str) -> dict:
        attempt = await self._attempt(owner, card_id)
        await self._linking.confirm(owner, attempt, await self._to_link(owner, attempt), phone, code)
        self._audit.log("index.linked", attempt=attempt.id)
        return await self._view(owner, card_id)

    async def disconnect(self, owner: str, card_id: str) -> dict:
        """Forgets the person's tokens, asks Index to revoke them if it can, and ends every attempt of theirs."""
        await self._attempt(owner, card_id)
        connection = await self._store.connection(owner)
        revoked = False
        if connection is not None:
            await self._store.forget(owner)
            revoked = await self._revoked(connection)
        await self._attempts.end_all(owner)
        self._audit.log("index.disconnected", revoked=revoked)
        note = (
            None if revoked else "234 has forgotten the connection. To end it at Index too, remove 234 there."
        )
        return await self._view(owner, card_id, notice=note)

    async def _revoked(self, connection: Connection) -> bool:
        """Whether Index confirmed it revoked the refresh token (which ends the access token's grant too) and
        the access token; false when it offers no revocation or could not be asked."""
        registration = await self._store.registration_of_client(connection.client_id)
        if registration is None:
            return False
        tokens = ((connection.tokens.refresh, "refresh_token"), (connection.tokens.access, "access_token"))
        confirmed = []
        with suppress(IndexProblem):
            for token, hint in tokens:
                if token:
                    confirmed.append(await self._oauth.revoke(registration, token, hint))
        return bool(confirmed) and all(confirmed)
