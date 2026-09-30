# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tool calls of one model reply: keeping their ids distinct, and spotting a call that repeats an
earlier one in the same reply."""

import json
from typing import Any

from . import kinds
from .eventlog import Event
from .idempotency import FIELD as KEY_FIELD

REPEATED = "Not made again: the same request was already made earlier in this reply, and this is its result. "


def arguments_of(call: dict[str, Any]) -> dict[str, Any] | None:
    """The arguments as JSON, or None when they are not a JSON object."""
    try:
        parsed = json.loads(call["arguments"] or "{}", strict=False)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def used_ids(events: list[Event]) -> set[str]:
    return {
        call["id"] for e in events if e.type == kinds.ASSISTANT for call in e.payload.get("tool_calls", [])
    }


def with_distinct_ids(calls: list[dict[str, Any]], used: set[str], message: str) -> list[dict[str, Any]]:
    """A call's id names its result and, for a quote, its idempotency key, so no two calls of a chat may
    share one. A provider that leaves the id empty or numbers calls from zero in every reply gets the id of
    the reply (unique) in front of it."""
    seen = set(used)
    distinct = []
    for index, call in enumerate(calls):
        call_id = call["id"]
        if not call_id or call_id in seen:
            call_id = f"{message}-{index}-{call_id}".rstrip("-")
        seen.add(call_id)
        distinct.append({**call, "id": call_id})
    return distinct


def _request_of(call: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """What a call asks for: the tool and its arguments, apart from a key the model may still send."""
    arguments = arguments_of(call)
    if arguments is None:
        return None
    return call["name"], {k: v for k, v in arguments.items() if k != KEY_FIELD}


def earlier_twin(calls: list[dict[str, Any]], call: dict[str, Any]) -> dict[str, Any] | None:
    """The first call before this one, in the same reply, that asks for the same thing."""
    request = _request_of(call)
    if request is None:
        return None
    for other in calls:
        if other["id"] == call["id"]:
            return None
        if _request_of(other) == request:
            return other
    return None
