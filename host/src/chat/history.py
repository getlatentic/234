# SPDX-License-Identifier: AGPL-3.0-or-later
"""The log as the page shows it. The same rules run in the browser for live events (static/chat/thread.js):
streamed text belongs to the reply that finishes it, an aborted reply vanishes, a card shows its latest state,
and only the latest compaction is marked."""

import json
from dataclasses import dataclass
from typing import Any

from turns import fold, kinds
from turns.eventlog import Event


@dataclass
class Item:
    kind: str
    event: Event
    text: str = ""
    streaming: bool = False
    state: dict[str, Any] | None = None

    @property
    def script_id(self) -> str:
        return f"card-{self.event.seq}"

    @property
    def state_id(self) -> str:
        return f"state-{self.event.seq}"

    @property
    def arguments_json(self) -> str:
        return json.dumps(self.event.payload.get("arguments", {}), indent=1, ensure_ascii=False)

    @property
    def tool_state(self) -> str:
        """How a row starts out. Whether a refusal is a failure depends on what follows it, which the page
        settles in static/chat/tool-status.js; a stored refusal starts quiet."""
        payload = self.event.payload
        if not payload.get("is_error"):
            return "ok"
        return "stopped" if payload.get("cancelled") else "refused"

    @property
    def tool_state_word(self) -> str:
        return "" if self.tool_state == "ok" else self.tool_state

    @property
    def compaction_line(self) -> str:
        return COMPACTION_LINES[self.event.payload["trigger"] == kinds.TRIGGER_FALLBACK]

    @property
    def compaction_summary(self) -> str:
        """What the assistant remembers of the earlier messages, shown only when the person opens the line. A
        fallback kept no summary of its own to show."""
        payload = self.event.payload
        return "" if payload["trigger"] == kinds.TRIGGER_FALLBACK else payload["summary"]

    @property
    def note(self) -> str:
        """A card's note as the person reads it: what the card now shows, without the model's framing."""
        return self.event.payload.get("text", "").split("now shows: ", 1)[-1].rstrip(". ")


COMPACTION_LINES = {False: "Earlier messages were summarised", True: "Earlier messages were left out"}


def _finished_messages(events: list[Event]) -> set[str]:
    return {e.payload["message"] for e in events if e.type in (kinds.ASSISTANT, kinds.ROUND_ABORTED)}


def items(events: list[Event]) -> list[Item]:
    finished = _finished_messages(events)
    shown: list[Item] = []
    streaming: dict[str, Item] = {}
    cards: dict[str, Item] = {}
    for event in events:
        if event.type == kinds.TEXT and event.payload["message"] not in finished:
            item = streaming.get(event.payload["message"])
            if item is None:
                item = streaming[event.payload["message"]] = Item(kinds.ASSISTANT, event, streaming=True)
                shown.append(item)
            item.text += event.payload["text"]
        elif event.type == kinds.ASSISTANT and event.payload.get("text", "").strip():
            shown.append(Item(kinds.ASSISTANT, event, event.payload["text"]))
        elif event.type == kinds.CARD:
            cards[event.ref or ""] = card = Item(kinds.CARD, event)
            shown.append(card)
        elif event.type == kinds.CARD_STATE and event.ref in cards:
            cards[event.ref].state = event.payload["result"]
        elif event.type == kinds.COMPACTION:
            shown = [item for item in shown if item.kind != kinds.COMPACTION]
            shown.append(Item(kinds.COMPACTION, event))
        elif event.type in (kinds.USER, kinds.CARD_MESSAGE, kinds.CARD_CONTEXT, kinds.TOOL, kinds.NOTICE):
            shown.append(Item(event.type, event))
    return shown


def is_working(events: list[Event]) -> bool:
    return fold.open_turn(events) is not None
