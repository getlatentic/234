# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whether adding money to wallets is paused (migrations/0018_wallet_reconciliation.sql): it is while the
latest reconciliation that could read every provider found 234 holding less than it owes. A run that could
not read one leaves the pause as the last complete run left it.

The rule is held in the WHERE of the statement that opens a top-up, as `funding_open_sql`; `funding_paused` is
for saying why one was refused, and for the ops report."""

from ..db import Db

_LATEST_COMPLETE = "(SELECT MAX(r.seq) FROM wallet_reconciliation AS r WHERE r.gap_kobo IS NOT NULL)"
_PAUSED = f"EXISTS (SELECT 1 FROM wallet_reconciliation WHERE seq = {_LATEST_COMPLETE} AND short = 1)"


def funding_open_sql() -> str:
    return f"NOT {_PAUSED}"


async def funding_paused(db: Db) -> bool:
    row = await db.row(f"SELECT {_PAUSED} AS paused")
    return bool(row and row["paused"])
