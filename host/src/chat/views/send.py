# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ways into a chat: the person's message, and what a card says. Each is checked, rate limited per visitor
and handed to the chat's Durable Object, which is the only writer of its log."""

import json
from typing import Any

from django.http import Http404, HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from turns import kinds
from turns.inputs import InputRefused, clean_text

from ..access import chat_for, claim_chat
from ..backend import get_backend
from ..models import Chat, Event

TITLE_CHARS = 60
STATUS = {"empty": 422, "too_long": 422, "card_data": 422}


def json_body(request: HttpRequest) -> dict[str, Any]:
    try:
        parsed = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _checked(request: HttpRequest, limit_key: str | None) -> str | JsonResponse:
    """The message once it is clean and the visitor may send it (under `limit_key`, when there is one);
    otherwise the answer that refuses it."""
    try:
        text = clean_text(json_body(request).get("text"))
    except InputRefused as refused:
        return JsonResponse(
            {"error": refused.code, "message": str(refused)}, status=STATUS.get(refused.code, 422)
        )
    if limit_key is not None and not get_backend().rate_ok(limit_key):
        return JsonResponse(
            {"error": "rate_limited", "message": "Too many messages. Wait a minute."}, status=429
        )
    return text


def _deliver(chat: Chat, kind: str, text: str) -> JsonResponse:
    answer = get_backend().submit(chat.id, kind, text)
    if "error" in answer:
        return JsonResponse(answer, status=STATUS.get(answer["error"], 422))
    if not chat.title and kind == kinds.USER:
        chat.title = text[:TITLE_CHARS]
        chat.save(update_fields=["title"])
    return JsonResponse(answer)


def _forget_if_empty(chat: Chat, created: bool) -> None:
    if created and not Event.objects.filter(chat=chat).exists():
        chat.delete()


def _submit(request: HttpRequest, chat_id: str, kind: str, limit_key: str | None) -> JsonResponse:
    chat = chat_for(request, chat_id)
    checked = _checked(request, limit_key)
    return checked if isinstance(checked, JsonResponse) else _deliver(chat, kind, checked)


@require_POST
def send(request: HttpRequest, chat_id: str) -> JsonResponse:
    return _submit(request, chat_id, kinds.USER, request.owner)


@require_POST
def start(request: HttpRequest, chat_id: str) -> JsonResponse:
    """The first message of a chat that the page minted an id for. The chat is made here, once the message
    has passed its checks, and a second message to the same id (a double submit, a retry) joins that chat
    instead of making another. A message that ends up refused leaves no chat behind."""
    checked = _checked(request, request.owner)
    if isinstance(checked, JsonResponse):
        return checked
    chat, created = claim_chat(request.owner, chat_id)
    if chat.owner != request.owner:
        raise Http404
    try:
        answer = _deliver(chat, kinds.USER, checked)
    except Exception:
        _forget_if_empty(chat, created)
        raise
    if answer.status_code != 200:
        _forget_if_empty(chat, created)
    return answer


@require_POST
def card_message(request: HttpRequest, chat_id: str) -> JsonResponse:
    """A message a card posts into the chat (ui/message). It is recorded as the card's, never as the
    person's own words, and the model is asked to reply."""
    return _submit(request, chat_id, kinds.CARD_MESSAGE, request.owner)


@require_POST
def card_note(request: HttpRequest, chat_id: str) -> JsonResponse:
    """What a card leaves for the model (ui/update-model-context): kept for its next turn, shown as
    a note, and never a reason to reply. It has a limit of its own, so a card that repeats itself cannot fill
    the chat's log or the model's context, and it does not use up the person's messages."""
    return _submit(request, chat_id, kinds.CARD_CONTEXT, f"note:{request.owner}")
