# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT §4: one message in, the agent's reply out. A message without a contextId starts a chat for this Brand
and User; one with a contextId continues it only if it is theirs. The turn runs as it does for the chat page,
and the reply is what the assistant said, with the link where the person approves a payment when one waits.
A messageId seen before in the context gets the reply stored for it."""

import time
from dataclasses import dataclass
from typing import Any

from django.urls import reverse

from a2a import wire
from chat import pacing, tickets
from chat.backend import get_backend
from chat.models import Chat, Event
from config.sql import returning
from turns import fold, kinds

from .brands import Brand
from .errors import A2AError
from .identity import Caller
from .models import Context, Reply

WAIT_SECONDS = 100
TITLE_CHARS = 60
STILL_WORKING = "Still working on it. Send another message in a moment to hear the result."
APPROVE = "The person approves this payment here: {link}"


@dataclass(frozen=True)
class Incoming:
    message_id: str
    text: str
    context_id: str | None


TEXT_PART_FIELDS = {"text", "mediaType", "metadata", "filename"}


def _is_text(part: dict) -> bool:
    return (
        isinstance(part.get("text"), str)
        and set(part) <= TEXT_PART_FIELDS
        and part.get("mediaType", "text/plain") == "text/plain"
    )


def read(body: Any) -> Incoming:
    message = body.get("message") if isinstance(body, dict) else None
    if not isinstance(message, dict) or message.get("role") != "ROLE_USER":
        raise A2AError("INVALID_PARAMS", "The message must have role ROLE_USER.")
    if message.get("taskId"):
        raise A2AError("TASK_NOT_FOUND", "Task not found")
    parts = message.get("parts")
    if not isinstance(parts, list) or not parts or not all(isinstance(p, dict) for p in parts):
        raise A2AError("INVALID_PARAMS", "The message needs parts.")
    if not all(_is_text(p) for p in parts):
        raise A2AError("CONTENT_TYPE_NOT_SUPPORTED", "Only text parts are accepted.")
    text = "\n".join(str(p["text"]) for p in parts).strip()
    message_id, context_id = message.get("messageId"), message.get("contextId")
    if not text or not isinstance(message_id, str) or not message_id or len(message_id) > 200:
        raise A2AError("INVALID_PARAMS", "The message needs a messageId and non-blank text.")
    if context_id is not None and not isinstance(context_id, str):
        raise A2AError("INVALID_PARAMS", "Unknown contextId")
    return Incoming(message_id, text, context_id)


def _context(brand: Brand, caller: Caller, incoming: Incoming) -> Context:
    if incoming.context_id is None:
        chat = Chat.objects.create(owner=caller.owner, connectors=",".join(brand.connectors))
        return Context.objects.create(chat=chat, brand=brand.id, owner=caller.owner)
    found = Context.objects.filter(chat_id=incoming.context_id, brand=brand.id, owner=caller.owner).first()
    if found is None:
        raise A2AError("INVALID_PARAMS", "Unknown contextId")
    return found


def _claim(context: Context, message_id: str) -> Reply | None:
    """The stored reply for a repeated messageId, or None when this message is new (now recorded). One
    statement decides it: on D1 a losing insert raises its own exception type, not IntegrityError."""
    recorded = returning(
        f"INSERT INTO {Reply._meta.db_table} (context_id, message_id, message) VALUES (%s, %s, NULL)"
        " ON CONFLICT (context_id, message_id) DO NOTHING RETURNING id",
        [context.pk, message_id],
    )
    if recorded:
        return None
    seen = Reply.objects.get(context=context, message_id=message_id)
    if seen.message is None:
        raise A2AError("INVALID_PARAMS", "That message has no reply yet.")
    return seen


def _answer(chat: Chat, task: str, handoff: str) -> str:
    started = last = time.monotonic()
    while time.monotonic() - started < WAIT_SECONDS:
        events = [row.as_logged() for row in Event.objects.filter(chat_id=chat.id, task=task)]
        state = fold.task_state(events)
        if state in wire.STOPS_STREAM:
            said = "\n\n".join(
                a["parts"][0]["text"] for a in wire.artifacts(events) if a["parts"][0].get("text")
            )
            if state == "failed":
                return said or wire.last_error(events)
            if state == "input_required":
                return f"{said}\n\n{APPROVE.format(link=handoff)}".strip()
            return said or wire.FAILED_TEXT
        pacing.wait(pacing.poll_interval(time.monotonic() - last))
    return STILL_WORKING


def reply(request, brand: Brand, caller: Caller, incoming: Incoming) -> dict[str, Any]:
    context = _context(brand, caller, incoming)
    if (seen := _claim(context, incoming.message_id)) is not None:
        return seen.message
    answer = get_backend().submit(context.chat_id, kinds.USER, incoming.text)
    if "error" in answer:
        Reply.objects.filter(context=context, message_id=incoming.message_id).delete()
        raise A2AError("INVALID_PARAMS", answer["message"])
    chat = context.chat
    if not chat.title:
        chat.title = incoming.text[:TITLE_CHARS]
        chat.save(update_fields=["title"])
    handoff = request.build_absolute_uri(reverse("chat:join", args=[tickets.mint_share_token(chat.id)]))
    text = _answer(chat, answer["task"], handoff)
    message = {
        "messageId": f"r-{answer['task']}",
        "contextId": chat.id,
        "role": "ROLE_AGENT",
        "parts": [{"text": text}],
    }
    Reply.objects.filter(context=context, message_id=incoming.message_id).update(message=message)
    return message
