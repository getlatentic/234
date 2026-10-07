# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a message gets back once its turn has stopped (PACT §4, §5.5, §5.6): a message with what the assistant
said, and the link where the person approves a payment when one waits; under a delegation token, a receipt
with it. A turn whose tool calls needed scopes the token lacks gets a task in TASK_STATE_AUTH_REQUIRED that
names them instead, and the conversation stays open for the agent to send again with a new token."""

import time
from dataclasses import dataclass
from typing import Any

from a2a import wire
from chat import pacing
from chat.models import Event
from turns import fold, kinds, permissions
from turns.eventlog import Event as Logged

from . import receipts
from .brands import Brand
from .delegation import Delegation
from .identity import Caller

WAIT_SECONDS = 100
STILL_WORKING = "Still working on it. Send another message in a moment to hear the result."
APPROVE = "The person approves this payment here: {link}"
NEEDS_SCOPES = "This needs the person's permission first."
MISSING_SCOPES = "pact.missingScopes"
RECEIPT = "pact.receipt"


@dataclass(frozen=True)
class Turn:
    context_id: str
    task: str
    handoff: str
    """Where the person opens the chat to approve a payment."""


def settled(chat_id: str, task: str) -> list[Logged] | None:
    """The task's events once it has stopped, or None if it is still running when the wait is over."""
    started = last = time.monotonic()
    while time.monotonic() - started < WAIT_SECONDS:
        events = [row.as_logged() for row in Event.objects.filter(chat_id=chat_id, task=task)]
        if fold.task_state(events) in wire.STOPS_STREAM:
            return events
        pacing.wait(pacing.poll_interval(time.monotonic() - last))
    return None


def _spoken(events: list[Logged]) -> str:
    return "\n\n".join(a["parts"][0]["text"] for a in wire.artifacts(events) if a["parts"][0].get("text"))


def _said(events: list[Logged], handoff: str) -> str:
    said = _spoken(events)
    state = fold.task_state(events)
    if state == "failed":
        return said or wire.last_error(events)
    if state == "input_required":
        return f"{said}\n\n{APPROVE.format(link=handoff)}".strip()
    return said or wire.FAILED_TEXT


def _missing(events: list[Logged]) -> list[str]:
    return sorted(
        {s for e in events if e.type == kinds.TOOL for s in e.payload.get(permissions.MISSING_FIELD, [])}
    )


def _message(turn: Turn, text: str) -> dict[str, Any]:
    return {
        "messageId": f"r-{turn.task}",
        "contextId": turn.context_id,
        "role": "ROLE_AGENT",
        "parts": [{"text": text}],
    }


def body(
    turn: Turn, events: list[Logged] | None, brand: Brand, caller: Caller, delegation: Delegation | None
) -> dict[str, Any]:
    if events is None:
        return {"message": _message(turn, STILL_WORKING)}
    if missing := _missing(events):
        asking = _message(turn, _spoken(events) or NEEDS_SCOPES)
        status = {"state": "TASK_STATE_AUTH_REQUIRED", "message": asking}
        task = {"id": f"t-{turn.task}", "contextId": turn.context_id, "status": status}
        return {"task": {**task, "metadata": {MISSING_SCOPES: missing}}}
    message = _message(turn, _said(events, turn.handoff))
    if delegation is not None:
        message["metadata"] = {RECEIPT: receipts.receipt(delegation, brand, caller, events, time.time())}
    return {"message": message}
