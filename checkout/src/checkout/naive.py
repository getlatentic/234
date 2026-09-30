# SPDX-License-Identifier: AGPL-3.0-or-later
"""The control for the concurrency tests: an approval that reads the budget, decides in Python,
then writes, the way a transaction-less port written carelessly would. Reachable only when
ENABLE_TEST_ROUTES=1. It scopes by owner as the ledger does, so the tests show it overspends one owner's
daily limit where `Ledger.claim_approval` does not."""

from .clock import lagos_day_start
from .ledger import SPENDING_STATES, Ledger

_STATES = ", ".join(f"'{s}'" for s in SPENDING_STATES)


async def naive_approve(ledger: Ledger, quote_id: str) -> bool:
    db, now, owner = ledger._db, ledger._clock.now(), ledger.owner()
    quote = await db.row("SELECT * FROM quotes WHERE id = ? AND owner = ?", quote_id, owner)
    if quote is None or quote["state"] != "open":
        return False
    spent = await db.row(
        "SELECT COALESCE(SUM(amount_kobo), 0) AS spent FROM quotes "
        f"WHERE owner = ? AND approved_at >= ? AND state IN ({_STATES})",
        owner,
        lagos_day_start(now),
    )
    if spent["spent"] + quote["amount_kobo"] > ledger.limits.daily_kobo:
        return False
    await db.execute("UPDATE quotes SET state = 'approved', approved_at = ? WHERE id = ?", now, quote_id)
    return True
