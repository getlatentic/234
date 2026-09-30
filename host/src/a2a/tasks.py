# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finding a task's events, and following them: the A2A side of the same log the chat page reads."""

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from chat import pacing
from chat.models import Chat, Event
from turns import fold
from turns.eventlog import Event as LoggedEvent

from . import wire
from .errors import TaskNotFound

MAX_STREAM_SECONDS = 600
KEEPALIVE_SECONDS = 15
BATCH = 200


@dataclass(frozen=True)
class Task:
    id: str
    chat: Chat

    def events(self, after: int = 0) -> list[LoggedEvent]:
        rows = Event.objects.filter(chat_id=self.chat.id, task=self.id, seq__gt=after)
        return [row.as_logged() for row in rows]


def find(task_id: str, owner: str) -> Task:
    """The caller's task. Another caller's task does not exist for them."""
    chat_id = Event.objects.filter(task=task_id).values_list("chat_id", flat=True).first()
    chat = Chat.objects.filter(pk=chat_id, owner=owner).first() if chat_id else None
    if chat is None:
        raise TaskNotFound("There is no such task.")
    return Task(task_id, chat)


def sse(item: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(item, ensure_ascii=False)}\n\n".encode()


def follow(task: Task, handoff_url: str, first: dict[str, Any] | None = None) -> Iterator[bytes]:
    """The task as a stream: its snapshot, then each change, until it finishes or asks for the person.
    It reads the log the same way the chat page's stream does, so a caller may drop and subscribe again."""
    seen = task.events()
    state = wire.StreamState(task.id, task.chat.id, seen)
    snapshot = wire.snapshot(task.id, task.chat.id, seen, handoff_url)
    yield sse(first or {"task": snapshot})
    if fold.task_state(seen) in wire.STOPS_STREAM:
        return
    cursor = seen[-1].seq if seen else 0
    started = last_event = last_sent = time.monotonic()
    while time.monotonic() - started < MAX_STREAM_SECONDS:
        events = task.events(cursor)[:BATCH]
        for event in events:
            cursor = event.seq
            for item in state.updates(event, handoff_url):
                yield sse(item)
            if state.stops:
                return
        if events:
            last_event = last_sent = time.monotonic()
            continue
        if time.monotonic() - last_sent > KEEPALIVE_SECONDS:
            last_sent = time.monotonic()
            yield b": keepalive\n\n"
        pacing.wait(pacing.poll_interval(time.monotonic() - last_event))
