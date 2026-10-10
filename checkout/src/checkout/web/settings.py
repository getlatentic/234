# SPDX-License-Identifier: AGPL-3.0-or-later
"""What web search needs, from the environment (docs/web.md). All of it, or the connector offers `web_fetch`
alone. A half-set or malformed value never stops the Worker (the payment connectors are on it, and the
secrets are set one at a time): search stays off and `trouble` says why, for the Worker's log."""

from collections.abc import Callable
from dataclasses import dataclass, field

from .search import gateway_problem
from .sigv4 import Credentials

REGION = "us-east-1"
TARGET = "web-search-tool"
PER_DAY = 30
NAMES = ("SEARCH_GATEWAY_URL", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")


def _text(read: Callable[[str], str | None], name: str) -> str:
    return (read(name) or "").strip()


def trouble(read: Callable[[str], str | None]) -> str | None:
    """Why web search is off though some of it is set, or None (nothing set, or all of it right)."""
    given = [name for name in NAMES if _text(read, name)]
    if not given:
        return None
    if len(given) < len(NAMES):
        return f"web search is off: {', '.join(n for n in NAMES if n not in given)} not set"
    if problem := gateway_problem(_text(read, NAMES[0]), _text(read, "SEARCH_REGION") or REGION):
        return f"web search is off: {problem}"
    per_day = _text(read, "SEARCHES_PER_DAY")
    if per_day and (not per_day.isdecimal() or int(per_day) <= 0):
        return "web search is off: SEARCHES_PER_DAY is not a positive whole number"
    return None


@dataclass(frozen=True)
class SearchSettings:
    gateway_url: str
    credentials: Credentials = field(repr=False)
    target: str = TARGET
    region: str = REGION
    per_day: int = PER_DAY

    @classmethod
    def from_env(cls, read: Callable[[str], str | None]) -> SearchSettings | None:
        if trouble(read) or not all(_text(read, name) for name in NAMES):
            return None
        return cls(
            _text(read, NAMES[0]),
            Credentials(_text(read, NAMES[1]), _text(read, NAMES[2])),
            _text(read, "SEARCH_TARGET") or TARGET,
            _text(read, "SEARCH_REGION") or REGION,
            int(_text(read, "SEARCHES_PER_DAY") or PER_DAY),
        )
