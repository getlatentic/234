# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hour a fetched page or robots.txt is kept (migrations/0009_web_cache.sql)."""

from dataclasses import dataclass

from ..clock import Clock
from ..db import Db

TTL_MS = 3_600_000


@dataclass(frozen=True)
class Entry:
    status: int
    final_url: str
    title: str
    text: str
    truncated: bool
    fetched_at: int


class WebCache:
    def __init__(self, db: Db, clock: Clock) -> None:
        self._db, self._clock = db, clock

    async def get(self, url: str, kind: str) -> Entry | None:
        row = await self._db.row(
            "SELECT status, final_url, title, text, truncated, fetched_at FROM web_cache "
            "WHERE url = ? AND kind = ? AND fetched_at > ?",
            url,
            kind,
            self._clock.now() - TTL_MS,
        )
        return None if row is None else Entry(**{**row, "truncated": bool(row["truncated"])})

    async def put(self, url: str, kind: str, entry: Entry) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO web_cache (url, kind, status, final_url, title, text, truncated, "
            "fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            url,
            kind,
            entry.status,
            entry.final_url,
            entry.title,
            entry.text,
            int(entry.truncated),
            entry.fetched_at,
        )
        await self._db.execute("DELETE FROM web_cache WHERE fetched_at <= ?", self._clock.now() - TTL_MS)
