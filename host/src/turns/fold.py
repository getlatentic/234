# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the log says: what the runner does next, and how a task stands.

All of it is a function of the events, so a runner that starts on a half-finished turn (after a restart)
continues from the log and never from memory.
"""

from dataclasses import dataclass
from typing import Any

from . import kinds
from .eventlog import Event

AWAITING_APPROVAL = "awaiting_approval"


@dataclass(frozen=True)
class Idle:
    """Nothing is waiting on the runner."""


@dataclass(frozen=True)
class ModelRound:
    """The model is to be asked, with the log as it stands."""

    driver: Event


@dataclass(frozen=True)
class ToolRound:
    """Some of the calls the model made have no result yet."""

    assistant: Event
    calls: list[dict[str, Any]]


Action = Idle | ModelRound | ToolRound
FEEDS_MODEL = kinds.INPUTS | {kinds.TOOL}


def _unanswered(assistant: Event, events: list[Event]) -> list[dict[str, Any]]:
    answered = {e.payload["call_id"] for e in events if e.type == kinds.TOOL}
    return [c for c in assistant.payload.get("tool_calls", []) if c["id"] not in answered]


def next_action(events: list[Event]) -> Action:
    """Unanswered tool calls come first. Then anything the model has not yet been shown (an input, or
    a tool result) asks for a round: each reply records how far into the log it read (`upto`), so a
    message that arrived while the model was streaming is answered by the next round. A turn the person
    stopped records the same mark on its `turn.finished`, and the results it wrote for the calls it
    stopped are marked `cancelled`: neither asks for a round."""
    replies = [e for e in events if e.type == kinds.ASSISTANT]
    for reply in replies:
        if missing := _unanswered(reply, events):
            return ToolRound(reply, missing)
    seen = max(
        (e.payload.get("upto", 0) for e in events if e.type in (kinds.ASSISTANT, kinds.TURN_FINISHED)),
        default=0,
    )
    fresh = [e for e in events if e.type in FEEDS_MODEL and e.seq > seen and not e.payload.get("cancelled")]
    return ModelRound(fresh[-1]) if fresh else Idle()


def open_turn(events: list[Event]) -> Event | None:
    """The `turn.started` event of a turn that has not finished."""
    marks = [e for e in events if e.type in (kinds.TURN_STARTED, kinds.TURN_FINISHED)]
    return marks[-1] if marks and marks[-1].type == kinds.TURN_STARTED else None


def waiting_task(events: list[Event]) -> str | None:
    """The task that ended asking for the person, if nothing has started since."""
    marks = [e for e in events if e.type in (kinds.TURN_STARTED, kinds.TURN_FINISHED)]
    if (
        marks
        and marks[-1].type == kinds.TURN_FINISHED
        and marks[-1].payload["reason"] == kinds.INPUT_REQUIRED
    ):
        return marks[-1].payload["task"]
    return None


def card_phases(events: list[Event]) -> dict[str, str]:
    """Each card's latest phase, by quote id: what it was issued with, then every pushed state."""
    phases: dict[str, str] = {}
    for event in events:
        if event.type in (kinds.CARD, kinds.CARD_STATE) and event.ref:
            quote = event.payload.get("result", {}).get("structuredContent", {}).get("quote", {})
            phases[event.ref] = quote.get("phase", phases.get(event.ref, ""))
    return phases


def cards_awaiting_approval(events: list[Event], task: str) -> bool:
    phases = card_phases(events)
    return any(
        phases.get(e.ref or "") == AWAITING_APPROVAL
        for e in events
        if e.type == kinds.CARD and e.task == task
    )


def task_state(events: list[Event]) -> str:
    """The A2A-style state of one task from its own events: submitted, working, input_required,
    completed, failed or canceled. An input that came after the last turn ended puts the task back
    to submitted."""
    marks = [e for e in events if e.type in (kinds.TURN_STARTED, kinds.TURN_FINISHED)]
    if not marks:
        return "submitted"
    last = marks[-1]
    if last.type == kinds.TURN_STARTED:
        return "working"
    if any(e.type in kinds.INPUTS and e.seq > last.seq for e in events):
        return "submitted"
    return {
        kinds.INPUT_REQUIRED: "input_required",
        kinds.FAILED: "failed",
        kinds.MAX_ROUNDS: "failed",
        kinds.CANCELLED: "canceled",
    }.get(last.payload["reason"], "completed")
