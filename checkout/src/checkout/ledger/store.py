# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading quotes, as the owner of the call.

Every statement names the owner of the call (owner.py). A quote of another owner is not found, exactly as
one that does not exist, so a guessed quote id shows nothing.
"""

from typing import Any

from ..clock import Clock
from ..db import Db
from ..errors import DomainError
from ..owner import current_owner
from .records import CheckoutFacts, Limits, Quote, quote_of


class QuoteStore:
    def __init__(
        self,
        db: Db,
        clock: Clock,
        limits: Limits,
        quote_ttl_seconds: int,
        approval_secret: str,
        default_owner: str | None,
    ) -> None:
        """`default_owner` acts for a call that names none (local development and tests); None refuses it."""
        self._db = db
        self._clock = clock
        self.limits = limits
        self._ttl_ms = quote_ttl_seconds * 1000
        self._secret = approval_secret.encode()
        self._default_owner = default_owner

    def owner(self) -> str:
        owner = current_owner() or self._default_owner
        if owner is None:
            raise DomainError("OWNER_REQUIRED", "This call does not say whose it is, so nothing was done.")
        return owner

    def _scoped_key(self, key: str) -> str:
        """The idempotency key as stored: UNIQUE (connector, idempotency_key) spans every owner, so the
        owner goes in front and two owners never share a key."""
        return f"{self.owner()}:{key}"

    async def _expire_if_due(self, row: dict[str, Any]) -> dict[str, Any]:
        if row["state"] != "open" or self._clock.now() < row["expires_at"]:
            return row
        await self._db.execute(
            "UPDATE quotes SET state = 'expired' WHERE id = ? AND owner = ? AND state = 'open'",
            row["id"],
            row["owner"],
        )
        return await self._row(row["id"], row["owner"]) or row

    async def _row(self, quote_id: str, owner: str) -> dict[str, Any] | None:
        return await self._db.row("SELECT * FROM quotes WHERE id = ? AND owner = ?", quote_id, owner)

    async def get(self, quote_id: str) -> Quote | None:
        row = await self._row(quote_id, self.owner())
        return quote_of(await self._expire_if_due(row)) if row else None

    async def checkout_facts(self, quote_id: str) -> CheckoutFacts | None:
        """What the simulated checkout page shows for a quote, and the state its buttons need. The page is
        opened by holding an unguessable reference, not as an owner: this is the one read naming none."""
        row = await self._db.row("SELECT merchant, description, state FROM quotes WHERE id = ?", quote_id)
        return CheckoutFacts(row["merchant"], row["description"], row["state"]) if row else None

    async def require(self, quote_id: str, connector: str) -> Quote:
        quote = await self.get(quote_id)
        if quote is None:
            raise DomainError("QUOTE_NOT_FOUND", f"There is no quote {quote_id}.")
        if quote.connector != connector:
            raise DomainError(
                "WRONG_CONNECTOR",
                f"Quote {quote_id} belongs to the {quote.connector} connector, not {connector}.",
            )
        return quote

    async def _group_of(self, quote_id: str) -> str:
        row = await self._db.row("SELECT payer_group FROM quotes WHERE id = ?", quote_id)
        return row["payer_group"] if row else ""

    async def _must_get(self, quote_id: str) -> Quote:
        quote = await self.get(quote_id)
        if quote is None:
            raise RuntimeError(f"quote {quote_id} vanished")
        return quote
