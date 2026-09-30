# SPDX-License-Identifier: AGPL-3.0-or-later
"""How big a request is, in tokens: four characters to a token, corrected by what the provider last counted.

The endpoint reports the tokens of a request once it has answered, so each reply records the estimate made
before it and the count that came back. The ratio of the latest pair corrects the next estimate, which keeps
the estimate honest for text that costs more than four characters a token (Pidgin, Yoruba, the naira sign).
"""

import json
from typing import Any

from . import kinds
from .eventlog import Event

CHARS_PER_TOKEN = 4
MESSAGE_OVERHEAD = 4
LEAST_RATIO = 0.5
MOST_RATIO = 3.0


def text_tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


def message_tokens(message: dict[str, Any]) -> int:
    calls = message.get("tool_calls")
    return (
        MESSAGE_OVERHEAD
        + text_tokens(message.get("content") or "")
        + (text_tokens(json.dumps(calls)) if calls else 0)
    )


def request_tokens(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> int:
    """The estimate for a request before any correction: its messages and the tool definitions it carries."""
    return sum(message_tokens(m) for m in messages) + (text_tokens(json.dumps(tools)) if tools else 0)


def ratio_of(events: list[Event]) -> float:
    """The provider's count over our estimate at the latest reply that has both, or 1 when none has."""
    for event in reversed(events):
        payload = event.payload
        usage = payload.get("usage") or {}
        if event.type == kinds.ASSISTANT and payload.get("estimate") and usage.get("prompt_tokens"):
            return min(MOST_RATIO, max(LEAST_RATIO, usage["prompt_tokens"] / payload["estimate"]))
    return 1.0


def corrected(estimate: int, ratio: float) -> int:
    return round(estimate * ratio)
