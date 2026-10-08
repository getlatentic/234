# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where a log line comes from: the chat, the turn (its task id) and a hash of who owns the chat. A turn
binds them for the length of its loop, and every log line written meanwhile carries them (turns/logs.py), so
one turn can be followed through the host's lines and, by the task id in a header, through the connectors'
(docs/logs.md). Nothing here is the owner or a chat's content: the owner is a digest, and a task id names no
one."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Trace:
    chat: str = ""
    owner: str = ""
    task: str = ""


NOWHERE = Trace()
_current: ContextVar[Trace] = ContextVar("trace", default=NOWHERE)


def owner_tag(owner: str) -> str:
    """Twelve hex characters of a digest of the chat's owner: one person's lines can be told from another's,
    and nobody can be read back from them."""
    return hashlib.sha256(owner.encode()).hexdigest()[:12] if owner else ""


def current() -> Trace:
    return _current.get()


@contextmanager
def bound(chat: str, owner: str, task: str = "") -> Iterator[None]:
    """Inside the block, log lines and connector calls are of this chat and its owner (and this task)."""
    token = _current.set(Trace(chat, owner_tag(owner), task))
    try:
        yield
    finally:
        _current.reset(token)


def set_task(task: str) -> None:
    """The turn the bound chat is now running; '' when it has none."""
    _current.set(replace(_current.get(), task=task))
