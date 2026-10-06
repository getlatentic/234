# SPDX-License-Identifier: AGPL-3.0-or-later
"""Checking a quote again with its provider, as its owner, outside any request of that owner: when a webhook
names it, and every minute for a payment still pending (a webhook can be lost). Only an approved quote is
checked: the others have ended or have not started, and a webhook about them changes nothing."""

from ..audit import Audit
from ..clock import Clock
from ..db import Db
from ..flows.airtime import AirtimeFlow
from ..flows.context import Context
from ..flows.food import FoodFlow
from ..flows.payment import PaymentFlow
from ..flows.transfer import TransferFlow
from ..jobs import Jobs
from ..owner import acting_for

FLOWS = {
    "paystack-pay": PaymentFlow,
    "send-money": TransferFlow,
    "airtime": AirtimeFlow,
    "food-order": FoodFlow,
}
SWEEP_AFTER_MS = 30_000
SWEEP_LIMIT = 50


class Rechecks:
    def __init__(self, db: Db, contexts: dict[str, Context], clock: Clock, audit: Audit) -> None:
        self._db, self._contexts, self._clock, self._audit = db, contexts, clock, audit
        self.jobs: Jobs | None = None

    async def _pending(self, quote_id: str) -> dict | None:
        """The one read here that names no owner: the webhook does not know whose the quote is."""
        row = await self._db.row("SELECT owner, connector, state FROM quotes WHERE id = ?", quote_id)
        return row if row and row["state"] == "approved" and row["connector"] in FLOWS else None

    async def ask(self, quote_id: str | None, source: str) -> bool:
        if quote_id is None or await self._pending(quote_id) is None or self.jobs is None:
            self._audit.log("recheck.skipped", quote=quote_id, source=source)
            return False
        await self.jobs.send({"kind": "recheck", "quote": quote_id, "source": source})
        return True

    async def run(self, quote_id: str) -> None:
        row = await self._pending(quote_id)
        if row is None:
            return
        with acting_for(row["owner"]):
            await FLOWS[row["connector"]](self._contexts[row["connector"]]).verify(quote_id)
        self._audit.log("recheck.done", quote=quote_id)

    async def sweep(self) -> int:
        """Every approved quote that has waited a while is asked about again, and every open quote past its
        time is expired, so its ending is told though nobody reads it (a read expires a quote too)."""
        await self._db.execute(
            "UPDATE quotes SET state = 'expired' WHERE state = 'open' AND expires_at <= ?", self._clock.now()
        )
        rows = await self._db.rows(
            "SELECT id FROM quotes WHERE state = 'approved' AND approved_at < ? ORDER BY approved_at LIMIT ?",
            self._clock.now() - SWEEP_AFTER_MS,
            SWEEP_LIMIT,
        )
        for row in rows:
            await self.ask(row["id"], "sweep")
        return len(rows)
