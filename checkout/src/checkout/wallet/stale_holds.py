# SPDX-License-Identifier: AGPL-3.0-or-later
"""Giving back holds a crash left behind (docs/wallet.md, "Spending: hold, claim, release").

A hold and its claim are one approval request (spending.py `pay`): the `spend` entry, then the quote's one
UPDATE, then a release if the claim lost. A Worker stopped between the hold and either of the others leaves a
hold that paid no quote and was never given back. The minute cron gives such holds back once they are older
than HOLD_STALE_MS, oldest first and at most RELEASE_LIMIT a run.

The release is spending.py's own, so it is written only while no quote of that id is marked as paid from the
wallet: a claim that lands late and the reaper exclude each other in SQL, whichever runs first wins, and a
hold that paid a quote is never given back."""

from ..audit import Audit
from ..clock import Clock
from ..db import Db
from ..owner import acting_for
from .spending import WalletSpending

HOLD_STALE_MS = 5 * 60_000
"""A hold and its claim are a few statements of one request, done within seconds; five minutes leaves an
approval still running far more than it needs. A claim later than that loses to the release and the card
says so; the money is never both kept and given back."""
RELEASE_LIMIT = 50

_STALE = (
    "SELECT h.owner, h.ref, h.amount_kobo FROM wallet_entry AS h "
    "WHERE h.kind = 'spend' AND h.created_at <= ? "
    "AND NOT EXISTS (SELECT 1 FROM wallet_entry AS r WHERE r.owner = h.owner AND r.kind = 'release' "
    "AND r.ref = h.ref) "
    "AND NOT EXISTS (SELECT 1 FROM quotes AS q WHERE q.id = h.ref AND q.owner = h.owner "
    "AND json_extract(q.progress, '$.funding') = 'wallet') "
    "ORDER BY h.seq LIMIT ?"
)


class StaleHolds:
    def __init__(self, spending: WalletSpending, db: Db, clock: Clock, audit: Audit) -> None:
        self._spending = spending
        self._db = db
        self._clock = clock
        self._audit = audit

    async def release_due(self) -> int:
        """Gives back the holds past their time that paid no quote; how many this run gave back."""
        rows = await self._db.rows(_STALE, self._clock.now() - HOLD_STALE_MS, RELEASE_LIMIT)
        released = 0
        for row in rows:
            if not await self._spending.release(row["owner"], row["ref"]):
                continue
            released += 1
            with acting_for(row["owner"]):
                self._audit.log(
                    "wallet.hold.released_stale", quote=row["ref"], amount_kobo=row["amount_kobo"]
                )
        return released
