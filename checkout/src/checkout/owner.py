# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whose money a call touches.

The chat host sends the owner of each tool call in the `x-ledger-owner` header, over its service binding
with the bearer token. The value is an opaque key of 32 lowercase hex characters (a visitor's id); this
server never interprets it. `handle_mcp` reads it from that header and from nowhere else, and holds it for
the length of the call, so the ledger scopes every read and write by it.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

OWNER_HEADER = "x-ledger-owner"
DEFAULT_OWNER = "0" * 32
_SHAPE = re.compile(r"[0-9a-f]{32}")

_current: ContextVar[str | None] = ContextVar("ledger_owner", default=None)


def is_owner_key(value: object) -> bool:
    return isinstance(value, str) and _SHAPE.fullmatch(value) is not None


def current_owner() -> str | None:
    return _current.get()


@contextmanager
def acting_for(owner: str) -> Iterator[None]:
    """Everything awaited inside the block acts for `owner`; a concurrent call has its own."""
    if not is_owner_key(owner):
        raise ValueError("an owner is 32 lowercase hex characters")
    token = _current.set(owner)
    try:
        yield
    finally:
        _current.reset(token)
