# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT §4 and §5.5: one message in, the agent's reply out. A message without a contextId starts a chat for
this Brand and User; one with a contextId continues it only if it is theirs. Under a delegation token the
turn runs as the person's 234 account, within the token's scopes (turns/permissions.py), in a chat of that
account. A context begun without one moves, on its first delegated message, to a new chat of the account:
the first chat keeps its owner, so a link handed out for it never opens the account's chat. Once a context
runs as an account, it needs a token for that account. A messageId seen before in the context gets the reply
stored for it."""

from dataclasses import dataclass
from typing import Any

from django.urls import reverse

from chat import tickets
from chat.backend import get_backend
from chat.models import Chat
from config.sql import returning
from turns import kinds

from . import answers
from .brands import Brand
from .delegation import Delegation
from .errors import A2AError
from .identity import Caller
from .models import Context, Reply

TITLE_CHARS = 60
UNKNOWN_CONTEXT = "Unknown contextId"
NEEDS_DELEGATION = "This conversation runs as a 234 account: send it with that account's delegation token."
OTHER_ACCOUNT = "This conversation runs as another 234 account."


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


def _chat(brand: Brand, owner: str, payer_group: str = "") -> Chat:
    return Chat.objects.create(owner=owner, connectors=",".join(brand.connectors), payer_group=payer_group)


def _moved_to_account(found: Context, brand: Brand, account: str) -> Context:
    chat = _chat(brand, account)
    claimed = returning(
        "UPDATE pact_context SET account = %s, delegated_chat_id = %s WHERE chat_id = %s AND account = '' "
        "RETURNING chat_id",
        [account, chat.id, found.chat_id],
    )
    if not claimed:
        chat.delete()
    found.refresh_from_db()
    if found.account != account:
        raise A2AError("INVALID_PARAMS", OTHER_ACCOUNT)
    return found


def _context(brand: Brand, caller: Caller, incoming: Incoming, delegation: Delegation | None) -> Context:
    account = delegation.account if delegation else ""
    if incoming.context_id is None:
        chat = _chat(brand, account, "") if account else _chat(brand, caller.owner, caller.payer_group)
        return Context.objects.create(chat=chat, brand=brand.id, owner=caller.owner, account=account)
    found = Context.objects.filter(chat_id=incoming.context_id, brand=brand.id, owner=caller.owner).first()
    if found is None:
        raise A2AError("INVALID_PARAMS", UNKNOWN_CONTEXT)
    if found.account == account:
        return found
    if found.account:
        raise A2AError("INVALID_PARAMS", OTHER_ACCOUNT if account else NEEDS_DELEGATION)
    return _moved_to_account(found, brand, account)


def _claim(context: Context, message_id: str) -> Reply | None:
    """The stored reply for a repeated messageId, or None when this message is new (now recorded). One
    statement decides it: on D1 a losing insert raises its own exception type, not IntegrityError."""
    recorded = returning(
        f"INSERT INTO {Reply._meta.db_table} (context_id, message_id, answer) VALUES (%s, %s, NULL)"
        " ON CONFLICT (context_id, message_id) DO NOTHING RETURNING id",
        [context.pk, message_id],
    )
    if recorded:
        return None
    seen = Reply.objects.get(context=context, message_id=message_id)
    if seen.answer is None:
        raise A2AError("INVALID_PARAMS", "That message has no reply yet.")
    return seen


def _handoff(request, context: Context) -> str:
    """An account's chat opens for that account when it signs in; any other chat by a share link."""
    if context.account:
        return request.build_absolute_uri(reverse("chat:page", args=[context.running_chat_id]))
    return request.build_absolute_uri(reverse("chat:join", args=[tickets.mint_share_token(context.chat_id)]))


def reply(
    request, brand: Brand, caller: Caller, incoming: Incoming, delegation: Delegation | None
) -> dict[str, Any]:
    """The reply body: {"message": …} or, for a step-up, {"task": …}."""
    context = _context(brand, caller, incoming, delegation)
    if (seen := _claim(context, incoming.message_id)) is not None:
        return seen.answer
    chat_id = context.running_chat_id
    scopes = sorted(delegation.scopes) if delegation else []
    answer = get_backend().submit(chat_id, kinds.USER, incoming.text, scopes=scopes)
    if "error" in answer:
        Reply.objects.filter(context=context, message_id=incoming.message_id).delete()
        raise A2AError("INVALID_PARAMS", answer["message"])
    Chat.objects.filter(pk=chat_id, title="").update(title=incoming.text[:TITLE_CHARS])
    turn = answers.Turn(context.chat_id, answer["task"], _handoff(request, context))
    body = answers.body(turn, answers.settled(chat_id, turn.task), brand, caller, delegation)
    Reply.objects.filter(context=context, message_id=incoming.message_id).update(answer=body)
    return body
