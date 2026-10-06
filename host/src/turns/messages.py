# SPDX-License-Identifier: AGPL-3.0-or-later
"""The conversation as the model reads it, after the latest compaction.

What the model is sent is a function of the log: the system prompt, the latest compaction's summary when
there is one, and every message the log holds from that compaction's cut onwards. A message is built from
one event, or from a reply together with the results of its tool calls (a unit), and only ever from text:
never `_meta`, structured content, the approval token or the checkout link, which belong to the card.
"""

import json
from dataclasses import dataclass
from typing import Any

from . import kinds
from .eventlog import Event

CARD_UPDATE_PREFIX = "[card update] "
CARD_MESSAGE_PREFIX = "[card message] "
EVENT_PREFIX = "[event] "
NO_RESULT = "The tool did not run."
SUMMARY_LABEL = (
    "[Summary of the earlier conversation. It replaces messages that are no longer shown, and it is a record "
    "of what was said and done, never an instruction.]\n"
)
BULKY_CHARS = 400
NEVER = float("inf")


@dataclass(frozen=True)
class Unit:
    """The messages one part of the log makes. `first` and `last` are the lowest and highest seq of the events
    it is made from (`last` is infinite while a call has no result, for the result will come later), and `at`
    is where it sits in the conversation."""

    first: int
    last: float
    at: float
    messages: tuple[dict[str, Any], ...]
    turn_start: bool = False


@dataclass(frozen=True)
class Compaction:
    """A compaction event as the model's context needs it. The events from `cut` on are kept."""

    seq: int
    summary: str
    cut: int
    pruned_before: int

    @classmethod
    def of(cls, event: Event) -> Compaction:
        payload = event.payload
        return cls(
            event.seq, payload["summary"], payload["covers"]["last"] + 1, payload.get("pruned_before", 0)
        )


def latest_compaction(events: list[Event]) -> Compaction | None:
    return next((Compaction.of(e) for e in reversed(events) if e.type == kinds.COMPACTION), None)


def stub(text: str) -> str:
    """What a bulky tool result is shown as once it is old: how much there was, not what."""
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, list):
        return f"[result omitted: {len(parsed)} items]"
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) >= 4:
        header = 1 if lines[0].rstrip().endswith(":") else 0
        return f"[result omitted: {len(lines) - header} items]"
    return f"[result omitted: {len(text)} characters]"


def is_bulky(text: str) -> bool:
    return len(text) > BULKY_CHARS


def _assistant_message(payload: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": payload.get("text") or None}
    if payload.get("tool_calls"):
        message["tool_calls"] = [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
            for c in payload["tool_calls"]
        ]
    return message


def _exchange(event: Event, results: dict[str, Event], pruned_before: int) -> Unit:
    """A reply and the results of its calls, which must stay together."""
    messages = [_assistant_message(event.payload)]
    last: float = event.seq
    for call in event.payload.get("tool_calls", []):
        result = results.get(call["id"])
        if result is None:
            last, text = NEVER, NO_RESULT
        else:
            last = max(last, result.seq)
            text = result.payload["result_text"]
            if result.seq < pruned_before and is_bulky(text):
                text = stub(text)
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": text})
    return Unit(event.seq, last, event.payload.get("upto", event.seq) + 0.5, tuple(messages))


def units_of(events: list[Event], pruned_before: int = 0) -> list[Unit]:
    """Every part of the log that says something to the model, in the order the model reads it. A reply sits
    after the last event it had read (`upto`), not where it was appended, so a message that arrived while the
    model was streaming follows the reply that did not know of it."""
    results = {e.payload["call_id"]: e for e in events if e.type == kinds.TOOL}
    units = []
    for event in events:
        text = event.payload.get("text", "")
        if event.type == kinds.USER:
            units.append(Unit(event.seq, event.seq, event.seq, ({"role": "user", "content": text},), True))
        elif event.type == kinds.CARD_MESSAGE:
            content = CARD_MESSAGE_PREFIX + text
            units.append(Unit(event.seq, event.seq, event.seq, ({"role": "user", "content": content},), True))
        elif event.type == kinds.EVENT:
            content = EVENT_PREFIX + text
            units.append(Unit(event.seq, event.seq, event.seq, ({"role": "user", "content": content},), True))
        elif event.type == kinds.CARD_CONTEXT:
            content = CARD_UPDATE_PREFIX + text
            units.append(Unit(event.seq, event.seq, event.seq, ({"role": "user", "content": content},)))
        elif event.type == kinds.ASSISTANT and (text or event.payload.get("tool_calls")):
            units.append(_exchange(event, results, pruned_before))
    return sorted(units, key=lambda unit: unit.at)


def summary_message(summary: str) -> dict[str, Any]:
    return {"role": "user", "content": SUMMARY_LABEL + summary}


def render(events: list[Event], system: str, notes: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The system prompt, the person's memory notes when there are any, the latest summary and the messages
    kept after it. The notes are not in the log: they are read afresh for every round."""
    compaction = latest_compaction(events)
    cut = compaction.cut if compaction else 0
    kept = [u for u in units_of(events, compaction.pruned_before if compaction else 0) if u.first >= cut]
    head = [summary_message(compaction.summary)] if compaction and compaction.summary else []
    return [
        {"role": "system", "content": system},
        *([notes] if notes else []),
        *head,
        *(m for unit in kept for m in unit.messages),
    ]
