# SPDX-License-Identifier: AGPL-3.0-or-later
"""The kinds of event in a chat's log. The log is the conversation: every client, the model's context
and the A2A view are folds of it."""

USER = "user"
CARD_MESSAGE = "card_message"
CARD_CONTEXT = "card_context"
EVENT = "event"
TURN_STARTED = "turn.started"
TURN_FINISHED = "turn.finished"
TURN_RESUMED = "turn.resumed"
TEXT = "text"
ASSISTANT = "assistant"
TOOL = "tool"
TOOL_STARTED = "tool.started"
CARD = "card"
CARD_STATE = "card_state"
NOTICE = "notice"
ROUND_ABORTED = "round.aborted"
COMPACTION = "compaction"

INPUTS = frozenset({USER, CARD_MESSAGE, EVENT})
DRIVERS = frozenset({USER, CARD_MESSAGE, EVENT, ASSISTANT, TOOL})

COMPLETED = "completed"
INPUT_REQUIRED = "input_required"
FAILED = "failed"
MAX_ROUNDS = "max_rounds"
CANCELLED = "cancelled"

NO_PROGRESS = "no_progress"
RESUMES_EXHAUSTED = "resumes_exhausted"

TRIGGER_AUTO = "auto"
TRIGGER_MANUAL = "manual"
TRIGGER_FALLBACK = "fallback"
