# SPDX-License-Identifier: AGPL-3.0-or-later
"""The events a summary is to cover, written out for the summariser.

Each event becomes one labelled line, so the summariser reads a record and does not take it for a
conversation to continue. Card events are written from the quote's own facts only: the approval token, the
checkout link and every other field of a card stay out. A tool result is not written at all, only whether the
call succeeded: merchant names, menus and whatever else a connector returns are text an instruction can be
planted in, and what matters of a result (the quote, its amount and its state) is on the card. Everything
is scrubbed.
"""

from typing import Any

from .. import kinds
from ..eventlog import Event
from .quotes import view_of
from .scrub import scrubbed

ARGUMENT_CHARS = 300


def _arguments(call: dict[str, Any]) -> str:
    return scrubbed(call["arguments"] or "{}")[:ARGUMENT_CHARS]


def _assistant(event: Event) -> list[str]:
    lines = []
    if text := event.payload.get("text", "").strip():
        lines.append(f"[Assistant]: {scrubbed(text)}")
    lines += [
        f"[Assistant called]: {c['name']}({_arguments(c)})" for c in event.payload.get("tool_calls", [])
    ]
    return lines


def _tool(event: Event) -> str:
    return f"[Tool result]: {'refused' if event.payload.get('is_error') else 'ok'}"


def _quote(event: Event) -> str:
    quote = view_of(event)
    details = quote.get("details") or {}
    what = details.get("readBack") or quote.get("description") or ""
    amount = (quote.get("amount") or {}).get("display", "")
    note = quote.get("message") or ""
    kind = "made" if event.type == kinds.CARD else "update"
    line = f"[Quote {kind}]: {event.ref} is {quote.get('phase', '')}, {amount}, {what}. {note}"
    return scrubbed(line.strip())


def lines_of(event: Event) -> list[str]:
    text = scrubbed(event.payload.get("text", ""))
    match event.type:
        case kinds.USER:
            return [f"[Person]: {text}"]
        case kinds.CARD_MESSAGE:
            return [f"[Card message]: {text}"]
        case kinds.CARD_CONTEXT:
            return [f"[Card update]: {text}"]
        case kinds.ASSISTANT:
            return _assistant(event)
        case kinds.TOOL:
            return [_tool(event)]
        case kinds.CARD | kinds.CARD_STATE if view_of(event):
            return [_quote(event)]
    return []


def transcript(events: list[Event]) -> str:
    return "\n".join(line for event in events for line in lines_of(event))
