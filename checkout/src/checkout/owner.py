# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whose money a call touches, and whose notes.

The chat host sends the owner of each tool call in the `x-ledger-owner` header, over its service binding
with the bearer token. The value is an opaque key of 32 lowercase hex characters (a visitor's id); this
server never interprets it. `handle_mcp` reads it from that header and from nowhere else, and holds it for
the length of the call, so the ledger scopes every read and write by it.

An outside personal agent's chats also carry a payer group in `x-ledger-group` (the same shape of key): the
people one agent speaks for are owners of their own, and the group caps what they spend together each day.

Memory has a header of its own, `x-memory-owner`, which the host sends only for a signed-in account. The
memory connector reads that owner and no other, so a call with none, an anonymous visitor's, reaches no note;
the wallet reads it too (wallet/access.py), so a visitor reaches no wallet.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

OWNER_HEADER = "x-ledger-owner"
MEMORY_OWNER_HEADER = "x-memory-owner"
GROUP_HEADER = "x-ledger-group"
TASK_HEADER = "x-task-id"
DEFAULT_OWNER = "0" * 32
_SHAPE = re.compile(r"[0-9a-f]{32}")
_TASK_SHAPE = re.compile(r"[A-Za-z0-9_-]{1,64}")

_current: ContextVar[str | None] = ContextVar("ledger_owner", default=None)
_memory: ContextVar[str | None] = ContextVar("memory_owner", default=None)
_group: ContextVar[str] = ContextVar("payer_group", default="")
_task: ContextVar[str] = ContextVar("task_id", default="")


def is_owner_key(value: object) -> bool:
    return isinstance(value, str) and _SHAPE.fullmatch(value) is not None


def current_owner() -> str | None:
    return _current.get()


def current_group() -> str:
    return _group.get()


@contextmanager
def acting_for(owner: str, group: str = "") -> Iterator[None]:
    """Everything awaited inside the block acts for `owner`, in payer `group` ('' for none); a concurrent
    call has its own."""
    if not is_owner_key(owner) or (group and not is_owner_key(group)):
        raise ValueError("an owner and a group are 32 lowercase hex characters")
    token, grouped = _current.set(owner), _group.set(group)
    try:
        yield
    finally:
        _group.reset(grouped)
        _current.reset(token)


def current_memory_owner() -> str | None:
    return _memory.get()


@contextmanager
def remembering_for(owner: str) -> Iterator[None]:
    """Memory acts for `owner` inside the block. Only a signed-in account has this: the host sends the
    memory owner header for an account and for nobody else."""
    if not is_owner_key(owner):
        raise ValueError("an owner is 32 lowercase hex characters")
    token = _memory.set(owner)
    try:
        yield
    finally:
        _memory.reset(token)


def current_task() -> str:
    return _task.get()


def task_of(value: str | None) -> str:
    """The turn's id from the task header, '' when it is absent or not an id: it only labels log lines, so a
    malformed one is dropped, not refused."""
    return value if value is not None and _TASK_SHAPE.fullmatch(value) else ""


@contextmanager
def in_task(task: str) -> Iterator[None]:
    """Audit lines written inside the block carry `task`, the host's id of the turn that made the call."""
    token = _task.set(task)
    try:
        yield
    finally:
        _task.reset(token)
