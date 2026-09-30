# SPDX-License-Identifier: AGPL-3.0-or-later
"""The daily cap on model calls, for each visitor and for everyone.

D1 has no transactions, so a check and its use are one conditional UPDATE: with several turns running
at once the cap still holds.
"""

from datetime import UTC, datetime

from .db import Db

GLOBAL_SCOPE = "global"


def day_of(at_ms: int) -> str:
    return datetime.fromtimestamp(at_ms / 1000, UTC).date().isoformat()


async def _take(db: Db, scope: str, day: str, cap: int) -> bool:
    if cap <= 0:
        return True
    await db.execute("INSERT OR IGNORE INTO chat_budget (scope, day, used) VALUES (?, ?, 0)", scope, day)
    changed = await db.execute(
        "UPDATE chat_budget SET used = used + 1 WHERE scope = ? AND day = ? AND used < ?", scope, day, cap
    )
    return changed == 1


async def _give_back(db: Db, scope: str, day: str) -> None:
    await db.execute(
        "UPDATE chat_budget SET used = used - 1 WHERE scope = ? AND day = ? AND used > 0", scope, day
    )


async def take_model_call(db: Db, visitor: str, at_ms: int, visitor_cap: int, global_cap: int) -> str | None:
    """None when the call may go ahead, otherwise which cap said no: "visitor" or "global"."""
    day = day_of(at_ms)
    if not await _take(db, visitor, day, visitor_cap):
        return "visitor"
    if not await _take(db, GLOBAL_SCOPE, day, global_cap):
        if visitor_cap > 0:
            await _give_back(db, visitor, day)
        return "global"
    return None
