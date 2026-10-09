# SPDX-License-Identifier: AGPL-3.0-or-later
"""The research runs and their chats (chat_research, and a chat_chat row for each, whose `parent` names the
chat it researches for)."""

import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..db import Db

RUNNING, DONE, TIMED_OUT, FAILED = "running", "done", "timed_out", "failed"
CONNECTORS = "knowledge,web"
DAY_MS = 86_400_000


def stamp(milliseconds: int) -> str:
    """A time as Django stores a DateTimeField."""
    return datetime.fromtimestamp(milliseconds / 1000, UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


class ResearchStore:
    def __init__(self, db: Db, clock: Callable[[], int]) -> None:
        self._db, self._clock = db, clock

    async def parent_of_run(self, parent: str) -> dict[str, Any] | None:
        return await self._db.row("SELECT owner, payer_group FROM chat_chat WHERE id = ?", parent)

    async def start(self, parent: str, owner: str, payer_group: str, question: str, seconds: int) -> str:
        run, now = secrets.token_hex(16), self._clock()
        await self._db.execute(
            "INSERT INTO chat_chat (id, owner, title, created_at, connectors, payer_group, parent) "
            "VALUES (?, ?, '', ?, ?, ?, ?)",
            run, owner, stamp(now), CONNECTORS, payer_group, parent,
        )  # fmt: skip
        try:
            await self._db.execute(
                "INSERT INTO chat_research (chat_id, parent, owner, question, status, created_at, "
                "deadline_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                run, parent, owner, question, RUNNING, now, now + seconds * 1000,
            )  # fmt: skip
        except Exception:
            await self._db.execute("DELETE FROM chat_chat WHERE id = ?", run)
            raise
        return run

    async def get(self, run: str) -> dict[str, Any] | None:
        return await self._db.row(
            "SELECT chat_id AS id, parent, owner, question, status, created_at, deadline_at "
            "FROM chat_research WHERE chat_id = ?",
            run,
        )

    async def running_for(self, parent: str) -> dict[str, Any] | None:
        """The run of this chat that is still going: not finished, and not past its deadline."""
        return await self._db.row(
            "SELECT chat_id AS id, question FROM chat_research WHERE parent = ? AND status = ? "
            "AND deadline_at > ? LIMIT 1",
            parent, RUNNING, self._clock(),
        )  # fmt: skip

    async def started_today(self, owner: str) -> int:
        row = await self._db.row(
            "SELECT COUNT(*) AS n FROM chat_research WHERE owner = ? AND created_at > ?",
            owner, self._clock() - DAY_MS,
        )  # fmt: skip
        return int(row["n"]) if row else 0

    async def close(self, run: str, status: str) -> bool:
        """Marks the run finished. True for the call that did it: a run reports once."""
        changed = await self._db.execute(
            "UPDATE chat_research SET status = ?, finished_at = ? WHERE chat_id = ? AND status = ?",
            status, self._clock(), run, RUNNING,
        )  # fmt: skip
        return changed == 1

    async def runs_of(self, parent: str) -> list[str]:
        rows = await self._db.rows("SELECT chat_id FROM chat_research WHERE parent = ?", parent)
        return [r["chat_id"] for r in rows]

    async def forget(self, parent: str) -> None:
        """Deletes the runs of a chat and their chats (their events go with them)."""
        await self._db.execute("DELETE FROM chat_chat WHERE parent = ?", parent)
