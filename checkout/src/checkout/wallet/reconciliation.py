# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wallet's reconciliation (docs/wallet.md, "Reconciliation"; migrations/0018_wallet_reconciliation.sql):
what 234 owes every wallet (books.py) against what it holds at Bachs, Paystack and VTpass (treasury.py), run
once an hour by the minute cron and whenever an operator asks (GET /ops/wallet/reconcile).

The gap is owed less held. A run that read every provider and found a gap is short, and while the latest
such run is short new top-ups are refused (funding_pause.py): money taken into a treasury that does not
cover what it owes would only add to what it cannot pay. Each run is kept, so the report is also the
history. Disputes are 234's cost here, never a wallet's: Bachs' $15 per dispute, and what lost ones could
not hold."""

from dataclasses import dataclass
from typing import Any

from ..audit import Audit
from ..clock import Clock
from ..db import Db
from ..money import Kobo
from ..refunds.attention import needing_operator, summary
from .books import Books, books_of
from .funding_pause import funding_paused
from .treasury import Held, Treasury

EVERY_MS = 60 * 60_000
DISPUTE_FEE_USD = 15

_RECORD = (
    "INSERT INTO wallet_reconciliation (at, owed_kobo, bachs_kobo, paystack_kobo, vtpass_kobo, gap_kobo, "
    "withdrawing_kobo, disputes, open_disputes, open_disputed_kobo, written_off_kobo, short) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


@dataclass(frozen=True)
class Report:
    at: int
    books: Books
    held: Held
    gap_kobo: Kobo | None
    funding_paused: bool
    refunds: dict[str, Any]
    """The refunds only an operator can finish (refunds/attention.py): owed to payers, not to wallets."""

    @property
    def short(self) -> bool:
        return self.gap_kobo is not None and self.gap_kobo > 0

    def view(self) -> dict[str, Any]:
        books, held = self.books, self.held
        return {
            "at": self.at,
            "owedKobo": books.owed_kobo,
            "heldKobo": {
                "bachs": held.bachs_kobo,
                "paystack": held.paystack_kobo,
                "vtpass": held.vtpass_kobo,
            },
            "gapKobo": self.gap_kobo,
            "short": self.short,
            "fundingPaused": self.funding_paused,
            "withdrawingKobo": books.withdrawing_kobo,
            "disputes": {
                "count": books.disputes,
                "open": books.open_disputes,
                "openKobo": books.open_disputed_kobo,
                "writtenOffKobo": books.written_off_kobo,
                "feesUsd": books.disputes * DISPUTE_FEE_USD,
            },
            "refundsNeedingAnOperator": self.refunds,
        }


class Reconciliation:
    def __init__(self, db: Db, clock: Clock, treasury: Treasury, audit: Audit) -> None:
        self._db = db
        self._clock = clock
        self._treasury = treasury
        self._audit = audit

    async def run(self) -> Report:
        books, held = await books_of(self._db), await self._treasury.held()
        total = held.total_kobo
        gap = None if total is None else books.owed_kobo - total
        now = self._clock.now()
        await self._db.execute(
            _RECORD,
            now, books.owed_kobo, held.bachs_kobo, held.paystack_kobo, held.vtpass_kobo, gap,
            books.withdrawing_kobo, books.disputes, books.open_disputes, books.open_disputed_kobo,
            books.written_off_kobo, 1 if gap is not None and gap > 0 else 0,
        )  # fmt: skip
        refunds = summary(await needing_operator(self._db, now))
        report = Report(now, books, held, gap, await funding_paused(self._db), refunds)
        self._audit.log(
            "wallet.reconciled" if not report.short else "wallet.reconcile.short",
            owed_kobo=books.owed_kobo,
            gap_kobo=gap,
            written_off_kobo=books.written_off_kobo,
            disputes=books.disputes,
        )
        return report

    async def run_if_due(self) -> Report | None:
        """A run when none was made in the last hour."""
        row = await self._db.row("SELECT MAX(at) AS last FROM wallet_reconciliation")
        last = row["last"] if row else None
        if last is not None and self._clock.now() - last < EVERY_MS:
            return None
        return await self.run()
