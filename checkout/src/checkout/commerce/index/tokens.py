# SPDX-License-Identifier: AGPL-3.0-or-later
"""A person's Index token, when it is wanted: the stored one while it has time left, a refreshed one a
minute before it runs out and when Index answers 401. A refresh replaces the row only while it is the
version read, so two calls that refresh together keep one result; a refresh Index refuses ends the
connection and asks the person to connect again, while one that could not be tried (no answer) leaves it
for the next call."""

import asyncio
from collections.abc import Awaitable, Callable

from ...clock import Clock
from ...errors import DomainError
from .oauth import IndexOAuth, TokenRefused, Tokens
from .store import Connection, IndexStore
from .wire import IndexProblem, IndexUnauthorized, IndexUnreachable

EARLY_MS = 60_000
WAIT_ATTEMPTS = 20
WAIT_SECONDS = 0.05
NOT_CONNECTED = "INDEX_NOT_CONNECTED"
RECONNECT = "INDEX_RECONNECT"


def not_connected() -> DomainError:
    return DomainError(
        NOT_CONNECTED,
        "The person has not connected their Paystack Index account. Call connect_account for the merchant: "
        "its card is where they connect. Do not ask for a code or a password in the chat.",
    )


def reconnect() -> DomainError:
    return DomainError(
        RECONNECT,
        "Index no longer honours the person's connection. Nothing was charged. Call connect_account so they "
        "can connect again on its card.",
    )


class IndexTokens:
    def __init__(self, store: IndexStore, oauth: IndexOAuth, clock: Clock) -> None:
        self._store, self._oauth, self._clock = store, oauth, clock

    async def connection(self, owner: str) -> Connection:
        found = await self._store.connection(owner)
        if found is None:
            raise not_connected()
        return found

    async def usable(self, owner: str) -> Tokens:
        """The owner's tokens, renewed first when they are about to run out."""
        found = await self.connection(owner)
        if found.tokens.expires_at - EARLY_MS > self._clock.now():
            return found.tokens
        return await self._renew(found)

    async def _renew(self, found: Connection) -> Tokens:
        if not found.tokens.refresh:
            await self._store.forget(found.owner)
            raise reconnect()
        registration = await self._store.registration_of_client(found.client_id)
        if registration is None:
            await self._store.forget(found.owner)
            raise reconnect()
        if not await self._store.claim_refresh(found):
            return await self._renewed_by_another(found)
        try:
            renewed = await self._oauth.refresh(registration, found.tokens.refresh)
        except TokenRefused:
            await self._store.forget(found.owner)
            raise reconnect() from None
        except IndexProblem:
            await self._store.release_refresh(found)
            raise
        if await self._store.swap(found, renewed):
            return renewed
        return await self._newer(found)

    async def _newer(self, found: Connection) -> Tokens:
        """Another call renewed first: its tokens are the ones to use."""
        latest = await self._store.connection(found.owner)
        if latest is None:
            raise not_connected()
        return latest.tokens

    async def _renewed_by_another(self, found: Connection) -> Tokens:
        """Another call is refreshing this connection: wait for its tokens rather than spend the refresh
        token a second time."""
        for _ in range(WAIT_ATTEMPTS):
            await asyncio.sleep(WAIT_SECONDS)
            latest = await self._store.connection(found.owner)
            if latest is None:
                raise not_connected()
            if latest.version != found.version:
                return latest.tokens
        raise IndexUnreachable("Another request is still renewing the connection.")

    async def run[T](self, owner: str, work: Callable[[str], Awaitable[T]]) -> T:
        """`work(access_token)`, and once more with a renewed token if Index answered 401 (it did not act).
        A second 401 means the connection is no good."""
        tokens = await self.usable(owner)
        try:
            return await work(tokens.access)
        except IndexUnauthorized:
            current = await self.connection(owner)
            fresh = await self._renew(current) if current.tokens.access == tokens.access else current.tokens
        try:
            return await work(fresh.access)
        except IndexUnauthorized:
            await self._store.forget(owner)
            raise reconnect() from None
