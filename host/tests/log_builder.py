# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic chat logs for tests that need no database: the events a real chat would hold, in the order it
would hold them, built a turn at a time."""

import json
from typing import Any

from turns import kinds
from turns.eventlog import Event

START = 1_790_000_000_000


def quote_view(ref: str, phase: str, kobo: int, what: str, expires_ms: int | None = None) -> dict[str, Any]:
    naira = f"₦{kobo // 100:,}.{kobo % 100:02d}"
    quote: dict[str, Any] = {
        "id": ref,
        "phase": phase,
        "amount": {"kobo": kobo, "display": naira},
        "description": what,
        "merchant": what,
        "details": {"kind": "airtime", "readBack": f"{naira} {what}"},
        "message": "",
    }
    if expires_ms is not None:
        quote["expiresAt"] = _iso(expires_ms)
    return {"content": [{"type": "text", "text": f"Quote {ref}"}], "structuredContent": {"quote": quote}}


def _iso(ms: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Log:
    """`events` is what the model's context and the runner's folds read: every kind but streamed text."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.task = "t0"
        self._calls = 0
        self._replies = 0

    @property
    def last(self) -> int:
        return self.events[-1].seq if self.events else 0

    def add(
        self,
        type: str,
        payload: dict[str, Any] | None = None,
        task: str | None = None,
        ref: str | None = None,
    ) -> Event:
        event = Event(self.last + 1, type, task, ref, payload or {}, START + self.last)
        self.events.append(event)
        return event

    def user(self, text: str) -> Event:
        return self.add(kinds.USER, {"text": text}, task=self.task)

    def reply(
        self, text: str = "", calls: list[dict[str, Any]] | None = None, upto: int | None = None
    ) -> Event:
        self._replies += 1
        payload: dict[str, Any] = {
            "message": f"m{self._replies}",
            "text": text,
            "finish_reason": "tool_calls" if calls else "stop",
            "upto": self.last if upto is None else upto,
        }
        if calls:
            payload["tool_calls"] = calls
        return self.add(kinds.ASSISTANT, payload, task=self.task)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._calls += 1
        return {"id": f"call_{self._calls}", "name": name, "arguments": json.dumps(arguments)}

    def result(self, call: dict[str, Any], text: str, is_error: bool = False) -> Event:
        payload = {
            "call_id": call["id"],
            "server": "s",
            "tool": call["name"].split("__")[-1],
            "arguments": json.loads(call["arguments"]),
            "result_text": text,
            "is_error": is_error,
        }
        return self.add(kinds.TOOL, payload, task=self.task)

    def exchange(
        self, name: str, arguments: dict[str, Any], result: str, text: str = ""
    ) -> tuple[Event, Event]:
        call = self.call(name, arguments)
        return self.reply(text, [call]), self.result(call, result)

    def quote(
        self,
        ref: str,
        kobo: int,
        what: str,
        phase: str = "awaiting_approval",
        expires_ms: int | None = None,
        says: str = "",
    ) -> Event:
        """A reply that makes a quote: the call, its result, and the card."""
        self.exchange("s__create_quote", {"amount_kobo": kobo}, f"Quote {ref}: {what}.", says)
        return self.add(
            kinds.CARD,
            {"server": "s", "tool": "create_quote", "resource_uri": "ui://s/card.html",
             "result": quote_view(ref, phase, kobo, what, expires_ms)},
            task=self.task,
            ref=ref,
        )  # fmt: skip

    def state(self, ref: str, phase: str, kobo: int = 0, what: str = "") -> Event:
        return self.add(kinds.CARD_STATE, {"result": quote_view(ref, phase, kobo, what)}, ref=ref)

    def turn(self, said: str, answer: str) -> None:
        """A person's message and a plain answer to it."""
        self.user(said)
        self.add(kinds.TURN_STARTED, {"task": self.task}, task=self.task)
        self.reply(answer)
        self.add(kinds.TURN_FINISHED, {"task": self.task, "reason": "completed"}, task=self.task)

    def compaction(self, last: int, summary: str = "Earlier: nothing.", pruned_before: int = 0) -> Event:
        first = next(
            (e.payload["covers"]["last"] + 1 for e in reversed(self.events) if e.type == kinds.COMPACTION), 1
        )
        payload = {
            "covers": {"first": first, "last": last},
            "summary": summary,
            "pruned_before": pruned_before,
            "trigger": "auto",
        }
        return self.add(kinds.COMPACTION, payload, ref=f"compaction:{first}-{last}:{pruned_before}")
