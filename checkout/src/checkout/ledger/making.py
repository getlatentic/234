# SPDX-License-Identifier: AGPL-3.0-or-later
"""Making a quote, once per request.

Idempotency: UNIQUE (connector, idempotency_key), the key stored with its owner in front so two owners
never meet on one key; the loser of the insert reads the winner.
"""

import json

from ..db import UniqueViolation
from ..errors import DomainError
from ..ids import new_quote_id
from ..owner import current_group
from .records import NewQuote, Quote, quote_of
from .spend import SpendLimits


class QuoteMaking(SpendLimits):
    async def replay(self, connector: str, key: str, digest: str) -> Quote | None:
        """The quote an earlier request with this key made; a key reused for another request is refused."""
        row = await self._db.row(
            "SELECT * FROM quotes WHERE owner = ? AND connector = ? AND idempotency_key = ?",
            self.owner(),
            connector,
            self._scoped_key(key),
        )
        if row is None:
            return None
        if row["request_hash"] != digest:
            raise DomainError(
                "IDEMPOTENCY_CONFLICT",
                "That idempotency_key was already used for a different request. "
                "Use a new key for a new request.",
            )
        return quote_of(await self._expire_if_due(row))

    async def create(self, new: NewQuote) -> tuple[Quote, bool]:
        """Returns the quote and whether it is a replay of an earlier identical request."""
        replayed = await self.replay(new.connector, new.idempotency_key, new.request_hash)
        if replayed:
            return replayed, True
        await self.assert_quotable(new.amount_kobo)
        quote_id, now = new_quote_id(), self._clock.now()
        try:
            await self._db.execute(
                "INSERT INTO quotes (id, owner, payer_group, connector, kind, amount_kobo, currency,"
                " description, merchant, merchant_ref, details, progress, state, idempotency_key,"
                " request_hash, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'NGN', ?, ?, ?, ?, '{}', 'open', ?, ?, ?, ?)",
                quote_id,
                self.owner(),
                current_group(),
                new.connector,
                new.kind,
                new.amount_kobo,
                new.description,
                new.merchant,
                new.merchant_ref,
                json.dumps(new.details),
                self._scoped_key(new.idempotency_key),
                new.request_hash,
                now,
                now + self._ttl_ms,
            )
        except UniqueViolation:
            winner = await self.replay(new.connector, new.idempotency_key, new.request_hash)
            if winner is None:
                raise
            return winner, True
        return await self._must_get(quote_id), False
