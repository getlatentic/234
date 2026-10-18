# SPDX-License-Identifier: AGPL-3.0-or-later
"""What web search needs, from the environment (docs/web.md): `SEARCH_API_KEY`, and optionally `SEARCH_URL`.
Without the key the connector offers `web_fetch` alone. A malformed value never stops the Worker (the payment
connectors are on it, and the secrets are set one at a time): search stays off and `trouble` says why, for
the Worker's log."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .search import ENDPOINT, endpoint_problem

PER_DAY = 30
KEY = "SEARCH_API_KEY"
_KEY_SHAPE = re.compile(r"[\x21-\x7e]+")


def _text(read: Callable[[str], str | None], name: str) -> str:
    return (read(name) or "").strip()


def trouble(read: Callable[[str], str | None]) -> str | None:
    """Why web search is off though some of it is set, or None (nothing set, or all of it right)."""
    key, url = _text(read, KEY), _text(read, "SEARCH_URL")
    if not (key or url):
        return None
    if not key:
        return f"web search is off: {KEY} not set"
    if not _KEY_SHAPE.fullmatch(key):
        return f"web search is off: {KEY} has a space or a character a key does not have"
    if url and (problem := endpoint_problem(url)):
        return f"web search is off: {problem}"
    per_day = _text(read, "SEARCHES_PER_DAY")
    if per_day and (not per_day.isdecimal() or int(per_day) <= 0):
        return "web search is off: SEARCHES_PER_DAY is not a positive whole number"
    return None


@dataclass(frozen=True)
class SearchSettings:
    api_key: str = field(repr=False)
    url: str = ENDPOINT
    per_day: int = PER_DAY

    @classmethod
    def from_env(cls, read: Callable[[str], str | None]) -> SearchSettings | None:
        if trouble(read) or not _text(read, KEY):
            return None
        return cls(
            _text(read, KEY),
            _text(read, "SEARCH_URL") or ENDPOINT,
            int(_text(read, "SEARCHES_PER_DAY") or PER_DAY),
        )
