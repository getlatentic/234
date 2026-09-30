# SPDX-License-Identifier: AGPL-3.0-or-later
"""The chat log as A2A 1.0 sees it (HTTP+JSON binding, protobuf JSON): a task per unit of work, its state,
the model's replies as artifacts and what it is doing as status messages.

What an A2A caller may know is only what a person reading the reply would: text. A card event carries the
approval token and never leaves the host; a caller learns that a person is being asked, and where they can
be sent to answer (a handoff link the host mints), and nothing that lets it approve.
"""

from datetime import UTC, datetime
from typing import Any

from turns import fold, kinds
from turns.eventlog import Event

from .errors import InvalidParams

STATES = {
    "submitted": "TASK_STATE_SUBMITTED",
    "working": "TASK_STATE_WORKING",
    "input_required": "TASK_STATE_INPUT_REQUIRED",
    "completed": "TASK_STATE_COMPLETED",
    "failed": "TASK_STATE_FAILED",
    "canceled": "TASK_STATE_CANCELED",
}
FINAL = ("completed", "failed", "canceled")
STOPS_STREAM = ("input_required", *FINAL)
ANSWER = "answer"
WAITING_TEXT = "A payment is waiting for the person's approval. Ask again once they have approved it."
FAILED_TEXT = "The assistant could not finish."


def rfc3339(at_ms: int) -> str:
    return datetime.fromtimestamp(at_ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def text_part(text: str) -> dict[str, Any]:
    return {"text": text}


def agent_message(task: str, context: str, seq: int, parts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "messageId": f"{task}-{seq}",
        "contextId": context,
        "taskId": task,
        "role": "ROLE_AGENT",
        "parts": parts,
    }


def status(state: str, at_ms: int, message: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"state": STATES[state], "timestamp": rfc3339(at_ms)}
    if message is not None:
        body["message"] = message
    return body


def input_required_message(task: str, context: str, seq: int, handoff_url: str) -> dict[str, Any]:
    return agent_message(
        task,
        context,
        seq,
        [text_part(WAITING_TEXT), {"data": {"waiting": "approval", "handoff": handoff_url}}],
    )


def last_error(events: list[Event]) -> str:
    notices = [
        e.payload["text"] for e in events if e.type == kinds.NOTICE and e.payload.get("level") == "error"
    ]
    return notices[-1] if notices else FAILED_TEXT


def artifacts(events: list[Event]) -> list[dict[str, Any]]:
    """One artifact per model reply that has said something: its final text, or what has streamed so far."""
    texts: dict[str, str] = {}
    final: set[str] = set()
    for event in events:
        if event.type == kinds.TEXT:
            texts[event.payload["message"]] = texts.get(event.payload["message"], "") + event.payload["text"]
        elif event.type == kinds.ASSISTANT and event.payload["text"].strip():
            texts[event.payload["message"]] = event.payload["text"]
            final.add(event.payload["message"])
        elif event.type == kinds.ROUND_ABORTED:
            texts.pop(event.payload["message"], None)
    return [
        {"artifactId": message, "name": ANSWER, "parts": [text_part(text)]}
        for message, text in texts.items()
        if text.strip()
    ]


def history(events: list[Event], context: str, length: int) -> list[dict[str, Any]]:
    users = [e for e in events if e.type == kinds.USER]
    return [
        {
            "messageId": f"{e.task}-{e.seq}",
            "contextId": context,
            "taskId": e.task,
            "role": "ROLE_USER",
            "parts": [text_part(e.payload["text"])],
        }
        for e in users[-length:]
    ]


def snapshot(
    task: str, context: str, events: list[Event], handoff_url: str, history_length: int = 0
) -> dict[str, Any]:
    """The task as it stands: its state, what the model has said so far, and (asked for) what was asked."""
    state = fold.task_state(events)
    at = events[-1].at if events else 0
    message = None
    if state == "input_required":
        message = input_required_message(task, context, events[-1].seq, handoff_url)
    elif state == "failed":
        message = agent_message(task, context, events[-1].seq, [text_part(last_error(events))])
    body: dict[str, Any] = {"id": task, "contextId": context, "status": status(state, at, message)}
    if found := artifacts(events):
        body["artifacts"] = found
    if history_length > 0:
        body["history"] = history(events, context, history_length)
    return body


class StreamState:
    """What one stream has already told its client, so the next event is sent as a change."""

    def __init__(self, task: str, context: str, events: list[Event]) -> None:
        self.task, self.context = task, context
        self.started = {a["artifactId"] for a in artifacts(events)}
        self.events = list(events)

    def updates(self, event: Event, handoff_url: str) -> list[dict[str, Any]]:
        """The stream responses one new event of the task calls for (often none)."""
        self.events.append(event)
        handler = getattr(self, f"_{event.type.replace('.', '_')}", None)
        return handler(event, handoff_url) if handler else []

    def _working(self, event: Event, text: str | None = None) -> dict[str, Any]:
        message = agent_message(self.task, self.context, event.seq, [text_part(text)]) if text else None
        update = {
            "taskId": self.task,
            "contextId": self.context,
            "status": status("working", event.at, message),
        }
        return {"statusUpdate": update}

    def _turn_started(self, event: Event, _: str) -> list[dict[str, Any]]:
        return [self._working(event)]

    def _tool(self, event: Event, _: str) -> list[dict[str, Any]]:
        return [self._working(event, f"Using {event.payload['tool']}")]

    def _text(self, event: Event, _: str) -> list[dict[str, Any]]:
        message = event.payload["message"]
        appending = message in self.started
        self.started.add(message)
        return [self._artifact(message, event.payload["text"], append=appending, last=False)]

    def _assistant(self, event: Event, _: str) -> list[dict[str, Any]]:
        message, text = event.payload["message"], event.payload["text"]
        if not text.strip():
            return []
        streamed = message in self.started
        self.started.add(message)
        return [self._artifact(message, "" if streamed else text, append=streamed, last=True)]

    def _round_aborted(self, event: Event, _: str) -> list[dict[str, Any]]:
        self.started.discard(event.payload["message"])
        return []

    def _turn_finished(self, event: Event, handoff_url: str) -> list[dict[str, Any]]:
        state = fold.task_state(self.events)
        message = None
        if state == "input_required":
            message = input_required_message(self.task, self.context, event.seq, handoff_url)
        elif state == "failed":
            message = agent_message(self.task, self.context, event.seq, [text_part(last_error(self.events))])
        update = {"taskId": self.task, "contextId": self.context, "status": status(state, event.at, message)}
        return [{"statusUpdate": update}]

    def _artifact(self, message: str, text: str, *, append: bool, last: bool) -> dict[str, Any]:
        artifact = {"artifactId": message, "name": ANSWER, "parts": [text_part(text)]}
        update: dict[str, Any] = {"taskId": self.task, "contextId": self.context, "artifact": artifact}
        if append:
            update["append"] = True
        if last:
            update["lastChunk"] = True
        return {"artifactUpdate": update}

    @property
    def stops(self) -> bool:
        return fold.task_state(self.events) in STOPS_STREAM


def user_text(message: Any) -> str:
    """The words of a caller's message: text parts only. A caller is not a card and cannot say it is."""
    if not isinstance(message, dict):
        raise InvalidParams("The request has no message.")
    if message.get("role") not in ("ROLE_USER", "user"):
        raise InvalidParams("The message must be from the user (ROLE_USER).")
    parts = message.get("parts") if isinstance(message.get("parts"), list) else []
    texts = [p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)]
    if not texts or len(texts) != len(parts):
        raise InvalidParams("The message must consist of text parts.")
    return "\n".join(texts)
