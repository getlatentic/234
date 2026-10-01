# SPDX-License-Identifier: AGPL-3.0-or-later
"""The entries of memory, read and changed. Every statement here names the owner, and an entry of another
owner is not found, exactly as one that does not exist. Nothing here writes a new entry: that is
`Proposals.apply`, the one statement that turns a confirmed proposal into a row."""

import re
import unicodedata
from typing import Any

from ..clock import Clock
from ..db import Db
from ..errors import DomainError
from .entry import Entry
from .settings import MemorySettings

SEARCH_LIMIT = 5
MAX_QUERY_WORDS = 8
MIN_PREFIX_LENGTH = 3
PURGE_BATCH = 50
_WORD = re.compile(r"[^\W_]+")


def not_found() -> DomainError:
    return DomainError("MEMORY_NOT_FOUND", "There is no such note. Check the index for its id.")


def match_expression(query: str) -> str | None:
    """Words of the query ORed, each quoted so no character of it is FTS syntax; a word of three letters or
    more also matches a longer one that starts with it ("mum" finds "mummy")."""
    words = _WORD.findall(unicodedata.normalize("NFC", query).casefold())[:MAX_QUERY_WORDS]
    terms = [f'"{w}"*' if len(w) >= MIN_PREFIX_LENGTH else f'"{w}"' for w in words]
    return " OR ".join(terms) or None


class MemoryStore:
    def __init__(self, db: Db, clock: Clock, settings: MemorySettings) -> None:
        self._db, self._clock, self.settings = db, clock, settings

    async def index_rows(self, owner: str) -> list[dict[str, Any]]:
        """The one query behind the memory index: live rows, newest use first, from the index on
        (owner, deleted_at, last_used)."""
        return await self._db.rows(
            "SELECT id, kind, title, hook FROM memory_entry WHERE owner = ? AND deleted_at IS NULL "
            "ORDER BY last_used DESC LIMIT ?",
            owner, self.settings.max_entries,
        )  # fmt: skip

    async def live(self, owner: str) -> list[Entry]:
        rows = await self._db.rows(
            "SELECT * FROM memory_entry WHERE owner = ? AND deleted_at IS NULL "
            "ORDER BY last_used DESC LIMIT ?",
            owner, self.settings.max_entries,
        )  # fmt: skip
        return [Entry.of(row) for row in rows]

    async def count_live(self, owner: str) -> int:
        row = await self._db.row(
            "SELECT COUNT(*) AS n FROM memory_entry WHERE owner = ? AND deleted_at IS NULL", owner
        )
        return int(row["n"]) if row else 0

    async def get(self, owner: str, entry_id: str) -> Entry | None:
        row = await self._db.row(
            "SELECT * FROM memory_entry WHERE id = ? AND owner = ? AND deleted_at IS NULL", entry_id, owner
        )
        return Entry.of(row) if row else None

    async def require(self, owner: str, entry_id: str) -> Entry:
        entry = await self.get(owner, entry_id)
        if entry is None:
            raise not_found()
        return entry

    async def title_taken(self, owner: str, kind: str, title: str, besides: str | None = None) -> str | None:
        """The id of a live entry of this kind that already has this title (compared without case)."""
        row = await self._db.row(
            "SELECT id FROM memory_entry WHERE owner = ? AND kind = ? AND deleted_at IS NULL "
            "AND lower(title) = lower(?) AND id IS NOT ? LIMIT 1",
            owner, kind, title, besides,
        )  # fmt: skip
        return row["id"] if row else None

    async def touch(self, owner: str, entry_id: str) -> None:
        """Marks an entry as used now, which puts it first in the index."""
        await self._db.execute(
            "UPDATE memory_entry SET last_used = ? WHERE id = ? AND owner = ? AND deleted_at IS NULL",
            self._clock.now(), entry_id, owner,
        )  # fmt: skip

    async def search(self, owner: str, query: str, limit: int = SEARCH_LIMIT) -> list[Entry]:
        match = match_expression(query)
        if match is None:
            return []
        rows = await self._db.rows(
            "SELECT e.* FROM memory_fts f JOIN memory_entry e ON e.seq = f.rowid "
            "WHERE memory_fts MATCH ? AND e.owner = ? AND e.deleted_at IS NULL ORDER BY f.rank LIMIT ?",
            match, owner, limit,
        )  # fmt: skip
        return [Entry.of(row) for row in rows]

    async def forget(self, owner: str, entry_id: str) -> int:
        now = self._clock.now()
        return await self._db.execute(
            "UPDATE memory_entry SET deleted_at = ?, updated_at = ? WHERE id = ? AND owner = ? "
            "AND deleted_at IS NULL",
            now, now, entry_id, owner,
        )  # fmt: skip

    async def edit(self, owner: str, entry_id: str, title: str, hook: str) -> int:
        return await self._db.execute(
            "UPDATE memory_entry SET title = ?, hook = ?, updated_at = ? WHERE id = ? AND owner = ? "
            "AND deleted_at IS NULL",
            title, hook, self._clock.now(), entry_id, owner,
        )  # fmt: skip

    async def delete_everything(self, owner: str) -> int:
        """Erases every entry and every proposal of the owner for good: no undo."""
        answers = await self._db.batch(
            [
                ("DELETE FROM memory_entry WHERE owner = ?", (owner,)),
                ("DELETE FROM memory_proposal WHERE owner = ?", (owner,)),
            ]
        )
        return answers[0].changes

    async def purge(self) -> int:
        """Deletes for good what the retention period has passed: forgotten entries and proposals that have
        expired. A bounded batch per call, run after a write, so no schedule is needed."""
        now = self._clock.now()
        answers = await self._db.batch(
            [
                (
                    "DELETE FROM memory_entry WHERE seq IN (SELECT seq FROM memory_entry "
                    "WHERE deleted_at IS NOT NULL AND deleted_at < ? LIMIT ?)",
                    (now - self.settings.retention_ms, PURGE_BATCH),
                ),
                (
                    "DELETE FROM memory_proposal WHERE id IN (SELECT id FROM memory_proposal "
                    "WHERE expires_at < ? LIMIT ?)",
                    (now, PURGE_BATCH),
                ),
            ]
        )
        return sum(answer.changes for answer in answers)
