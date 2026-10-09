# SPDX-License-Identifier: AGPL-3.0-or-later
from django.db.models import Max, Q, QuerySet
from django.http import Http404, HttpRequest

from .models import Access, Chat


def chats_of(owner: str) -> QuerySet[Chat]:
    """The chats an owner made or was let into, the latest activity first."""
    let_in = Access.objects.filter(visitor=owner).values("chat_id")
    mine = Chat.objects.filter(Q(owner=owner) | Q(id__in=let_in), parent="")
    return mine.annotate(last=Max("events__created_at")).order_by("-last", "-created_at")


def chat_for(request: HttpRequest, chat_id: str) -> Chat:
    """The chat if the requester owns it or was let in; otherwise it does not exist for them."""
    chat = chats_of(request.owner).filter(pk=chat_id).first()
    if chat is None:
        raise Http404
    return chat


def claim_chat(owner: str, chat_id: str) -> tuple[Chat, bool]:
    """The chat stored under this id, made for `owner` if there is none yet (the second value says whether
    this call made it). Callers racing for one id all get the one chat: D1 reports the loser's insert as its
    own exception type, not Django's IntegrityError, so any failure is settled by looking again."""
    existing = Chat.objects.filter(pk=chat_id).first()
    if existing is not None:
        return existing, False
    try:
        return Chat.objects.create(id=chat_id, owner=owner), True
    except Exception:
        winner = Chat.objects.filter(pk=chat_id).first()
        if winner is None:
            raise
        return winner, False
