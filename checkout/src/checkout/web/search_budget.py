# SPDX-License-Identifier: AGPL-3.0-or-later
"""A person's web searches for the day (migrations/0010_web_search_use.sql). A search is paid for by the
search, so the count is taken before it is made, in one statement: searches that arrive together cannot pass
the cap."""

from datetime import UTC, datetime

from ..clock import Clock
from ..db import Db


class SearchBudget:
    def __init__(self, db: Db, clock: Clock, per_day: int) -> None:
        self._db, self._clock, self._per_day = db, clock, per_day

    def _day(self) -> str:
        return datetime.fromtimestamp(self._clock.now() / 1000, UTC).date().isoformat()

    async def take(self, owner: str) -> bool:
        """True when `owner` still had a search left today, and now has one less."""
        changed = await self._db.execute(
            "INSERT INTO web_search_use (owner, day, used) VALUES (?, ?, 1) "
            "ON CONFLICT (owner, day) DO UPDATE SET used = used + 1 WHERE used < ?",
            owner,
            self._day(),
            self._per_day,
        )
        return changed >= 1

    async def used(self, owner: str) -> int:
        row = await self._db.row(
            "SELECT used FROM web_search_use WHERE owner = ? AND day = ?", owner, self._day()
        )
        return int(row["used"]) if row else 0
