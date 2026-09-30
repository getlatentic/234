# SPDX-License-Identifier: AGPL-3.0-or-later
"""A chat's append-only log in D1: one INSERT takes the next seq, so any writer may append and the
unique (chat, seq) key refuses a duplicate. Events never change."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from . import kinds
from .db import Db

TABLE = "chat_event"
COLUMNS = "seq, type, task, ref, payload, created_at"

Clock = Callable[[], int]


@dataclass(frozen=True)
class Event:
    seq: int
    type: str
    task: str | None
    ref: str | None
    payload: dict[str, Any]
    at: int

    def wire(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "type": self.type,
            "task": self.task,
            "ref": self.ref,
            "payload": self.payload,
            "at": self.at,
        }


def _event(row: dict[str, Any]) -> Event:
    return Event(
        row["seq"],
        row["type"],
        row["task"] or None,
        row["ref"] or None,
        json.loads(row["payload"]),
        row["created_at"],
    )


class EventLog:
    def __init__(
        self,
        db: Db,
        chat_id: str,
        clock: Clock,
        on_append: Callable[[Event], Awaitable[None]] | None = None,
    ) -> None:
        self._db = db
        self.chat_id = chat_id
        self._clock = clock
        self._on_append = on_append

    async def append(
        self, type: str, payload: dict[str, Any], *, task: str | None = None, ref: str | None = None
    ) -> Event:
        at = self._clock()
        row = await self._db.row(
            f"INSERT INTO {TABLE} (chat_id, seq, type, task, ref, payload, created_at) "
            f"SELECT ?1, COALESCE(MAX(seq), 0) + 1, ?2, ?3, ?4, ?5, ?6 FROM {TABLE} WHERE chat_id = ?1 "
            "RETURNING seq",
            self.chat_id, type, task or "", ref or "", json.dumps(payload, ensure_ascii=False), at,
        )  # fmt: skip
        assert row is not None
        event = Event(row["seq"], type, task, ref, payload, at)
        if self._on_append is not None:
            await self._on_append(event)
        return event

    async def append_next_of_type(
        self, type: str, payload: dict[str, Any], *, ref: str, newest: int
    ) -> Event | None:
        """Appends an event of `type` only while `newest` is still the seq of the newest event of that type
        (0 for none) and no event of that type has this `ref`, all in the one statement that takes the seq: of
        two writers that mean the same thing, one appends and the other gets None."""
        at = self._clock()
        row = await self._db.row(
            f"INSERT INTO {TABLE} (chat_id, seq, type, task, ref, payload, created_at) "
            f"SELECT ?1, (SELECT COALESCE(MAX(seq), 0) + 1 FROM {TABLE} WHERE chat_id = ?1), "
            "?2, '', ?3, ?4, ?5 "
            f"WHERE (SELECT COALESCE(MAX(seq), 0) FROM {TABLE} WHERE chat_id = ?1 AND type = ?2) = ?6 "
            f"AND NOT EXISTS (SELECT 1 FROM {TABLE} WHERE chat_id = ?1 AND type = ?2 AND ref = ?3) "
            "RETURNING seq",
            self.chat_id, type, ref, json.dumps(payload, ensure_ascii=False), at, newest,
        )  # fmt: skip
        if row is None:
            return None
        event = Event(row["seq"], type, None, ref, payload, at)
        if self._on_append is not None:
            await self._on_append(event)
        return event

    async def read(self, after: int = 0, limit: int = 500) -> list[Event]:
        rows = await self._db.rows(
            f"SELECT {COLUMNS} FROM {TABLE} WHERE chat_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            self.chat_id, after, limit,
        )  # fmt: skip
        return [_event(r) for r in rows]

    async def context(self) -> list[Event]:
        """Every event the model's context and the turn state are built from: all but streamed text."""
        rows = await self._db.rows(
            f"SELECT {COLUMNS} FROM {TABLE} WHERE chat_id = ? AND type != ? ORDER BY seq",
            self.chat_id, kinds.TEXT,
        )  # fmt: skip
        return [_event(r) for r in rows]

    async def last_seq(self) -> int:
        row = await self._db.row(
            f"SELECT COALESCE(MAX(seq), 0) AS seq FROM {TABLE} WHERE chat_id = ?", self.chat_id
        )
        return int(row["seq"]) if row else 0

    async def newest_of_type(self, type: str) -> int:
        row = await self._db.row(
            f"SELECT COALESCE(MAX(seq), 0) AS seq FROM {TABLE} WHERE chat_id = ? AND type = ?",
            self.chat_id, type,
        )  # fmt: skip
        return int(row["seq"]) if row else 0

    async def erase(self) -> None:
        await self._db.execute(f"DELETE FROM {TABLE} WHERE chat_id = ?", self.chat_id)
