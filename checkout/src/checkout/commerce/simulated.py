# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated directory's merchants, in D1: the accounts they know and the answer they give an order.

An order is delivered unless a test route (`POST /test/merchant-order/<quote id>?outcome=`) set another answer
first. The first answer is written once, by the earlier of that route and the fulfilment that places the
order; only a pending one moves, to delivered or failed, so a merchant that answered keeps its answer."""

from ..clock import Clock
from ..db import Db
from .model import Outcome, OutcomeStatus
from .provider import AccountLookup

ANSWERS: dict[str, str] = {
    "delivered": "The merchant delivered the order.",
    "pending": "The merchant has not answered yet.",
    "failed": "The merchant could not fill the order.",
}


class SimMerchants:
    def __init__(self, db: Db, clock: Clock) -> None:
        self._db, self._clock = db, clock

    async def account(self, merchant_id: str, reference: str) -> AccountLookup | None:
        row = await self._db.row(
            "SELECT holder_name, due_kobo FROM sim_merchant_account WHERE merchant_id = ? AND reference = ?",
            merchant_id,
            reference,
        )
        return AccountLookup(row["holder_name"], row["due_kobo"]) if row else None

    async def outcome(self, quote_id: str) -> Outcome | None:
        row = await self._db.row(
            "SELECT outcome, description FROM sim_merchant_order WHERE quote_id = ?", quote_id
        )
        return Outcome(row["outcome"], row["description"]) if row else None

    async def place(self, quote_id: str) -> Outcome:
        """Takes the order once; a repeat finds the answer the first gave."""
        await self._write(quote_id, "delivered", "INSERT OR IGNORE")
        return await self._must(quote_id)

    async def preset(self, quote_id: str, outcome: OutcomeStatus) -> Outcome:
        """The test route's: the answer for an order not placed yet, or for one still pending."""
        await self._write(
            quote_id,
            outcome,
            "INSERT",
            " ON CONFLICT (quote_id) DO UPDATE SET outcome = excluded.outcome, description = "
            "excluded.description WHERE sim_merchant_order.outcome = 'pending'",
        )
        return await self._must(quote_id)

    async def _must(self, quote_id: str) -> Outcome:
        found = await self.outcome(quote_id)
        if found is None:
            raise RuntimeError(f"order {quote_id} vanished")
        return found

    async def _write(self, quote_id: str, outcome: str, verb: str, conflict: str = "") -> None:
        await self._db.execute(
            f"{verb} INTO sim_merchant_order (quote_id, outcome, description, created_at) "
            f"VALUES (?, ?, ?, ?){conflict}",
            quote_id,
            outcome,
            ANSWERS[outcome],
            self._clock.now(),
        )
