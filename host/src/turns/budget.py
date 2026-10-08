# SPDX-License-Identifier: AGPL-3.0-or-later
"""The daily caps on the model, for each visitor or account and for everyone: on calls, and on tokens.

D1 has no transactions, so a call's check and its use are one conditional UPDATE: with several turns running
at once the cap on calls still holds. The cap on tokens is read before a round and the round's tokens are
added after it, because what a round costs is known only then: a round that starts under the cap may end over
it, by one round at most, and the next is refused.
"""

from datetime import UTC, datetime

from .db import Db

GLOBAL_SCOPE = "global"
TOKENS = "tokens:"


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


async def _used(db: Db, scope: str, day: str) -> int:
    row = await db.row("SELECT used FROM chat_budget WHERE scope = ? AND day = ?", scope, day)
    return int(row["used"]) if row else 0


async def tokens_used_up(db: Db, owner: str, at_ms: int, owner_cap: int, global_cap: int) -> str | None:
    """None while `owner` and everyone are under today's token caps (a cap of 0 is none), otherwise which cap
    said no: "visitor" or "global"."""
    day = day_of(at_ms)
    if owner_cap > 0 and await _used(db, f"{TOKENS}{owner}", day) >= owner_cap:
        return "visitor"
    if global_cap > 0 and await _used(db, f"{TOKENS}{GLOBAL_SCOPE}", day) >= global_cap:
        return "global"
    return None


async def add_tokens(db: Db, owner: str, at_ms: int, tokens: int, owner_cap: int, global_cap: int) -> None:
    """Adds a round's tokens to today's count, for `owner` and for everyone (none where there is no cap)."""
    if tokens <= 0:
        return
    day = day_of(at_ms)
    for scope, cap in ((f"{TOKENS}{owner}", owner_cap), (f"{TOKENS}{GLOBAL_SCOPE}", global_cap)):
        if cap > 0:
            await db.execute(
                "INSERT OR IGNORE INTO chat_budget (scope, day, used) VALUES (?, ?, 0)", scope, day
            )
            await db.execute(
                "UPDATE chat_budget SET used = used + ? WHERE scope = ? AND day = ?", tokens, scope, day
            )
