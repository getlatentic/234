# SPDX-License-Identifier: AGPL-3.0-or-later
from functools import cache

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from config import runtime
from turns.settings import Settings

from .. import history, tickets
from ..access import chat_for, chats_of
from ..backend import get_backend
from ..context import tagline
from ..models import Access, Chat, Event, Research
from ..palette import GROUND, PRIMARY
from ..shell import render_shell
from ..starters import STARTERS

TRANSPORTS = ("ws", "sse")
MANIFEST_ICONS = (
    ("icon-192.png", "192x192", "any"),
    ("icon-512.png", "512x512", "any"),
    ("icon-maskable-512.png", "512x512", "maskable"),
)


@cache
def turn_settings() -> Settings:
    """Read once per process: the configuration of a running Worker does not change, and each setting is a
    call into JavaScript."""
    return Settings.from_env(runtime.get)


def _thread(request: HttpRequest, chat: Chat, events: list[Event], draft: bool) -> HttpResponse:
    logged = [e.as_logged() for e in events]
    return render(
        request,
        "chat/chat.html",
        {
            "chat": chat,
            "draft": draft,
            "items": history.items(logged),
            "last_seq": logged[-1].seq if logged else 0,
            "working": history.is_working(logged),
            "chats": chats_of(request.owner),
            "starters": STARTERS,
            "model_problem": turn_settings().model_problem(),
            "transport": request.GET.get("transport") if request.GET.get("transport") in TRANSPORTS else "",
        },
    )


@require_GET
def home(request: HttpRequest) -> HttpResponse:
    """The empty home: a composer for a chat that does not exist yet. It is the static shell (shell.py) that
    Workers static assets serve before the Worker is reached; this answers where the assets hold no copy
    (a stack that was not built, a test). The page mints the chat's id, the first message makes the row
    (views/send.py `start`), and until then nothing is stored."""
    return HttpResponse(render_shell(request))


@require_GET
def page(request: HttpRequest, chat_id: str) -> HttpResponse:
    chat = chat_for(request, chat_id)
    return _thread(request, chat, list(Event.objects.filter(chat=chat)), draft=False)


@require_POST
def delete(request: HttpRequest, chat_id: str) -> HttpResponse:
    chat = chat_for(request, chat_id)
    if chat.owner != request.owner:
        return HttpResponse(status=403)
    runs = list(Research.objects.filter(parent=chat.id).values_list("chat_id", flat=True))
    for chat_id in (chat.id, *runs):
        get_backend().erase(chat_id)
    with transaction.atomic():
        Chat.objects.filter(parent=chat.id).delete()
        chat.delete()
    return redirect("chat:index")


@require_POST
def share(request: HttpRequest, chat_id: str) -> JsonResponse:
    chat = chat_for(request, chat_id)
    path = reverse("chat:join", args=[tickets.mint_share_token(chat.id)])
    return JsonResponse({"url": request.build_absolute_uri(path), "expires_in": tickets.SHARE_TTL_SECONDS})


@require_GET
def join(request: HttpRequest, token: str) -> HttpResponse:
    chat_id = tickets.chat_for_share_token(token)
    chat = Chat.objects.filter(pk=chat_id).first() if chat_id else None
    if chat is None:
        return HttpResponse("This link has expired.", status=410, content_type="text/plain")
    if chat.owner != request.owner:
        Access.objects.get_or_create(chat=chat, visitor=request.owner)
    return redirect("chat:page", chat.id)


@require_GET
def manifest(request: HttpRequest) -> JsonResponse:
    request.wants_visitor_cookie = False
    name = settings.PRODUCT_NAME
    return JsonResponse(
        {
            "name": name,
            "short_name": name,
            "description": tagline(name),
            "start_url": reverse("chat:index"),
            "display": "standalone",
            "background_color": GROUND["light"],
            "theme_color": PRIMARY,
            "icons": [
                {"src": static(f"chat/brand/{file}"), "sizes": size, "type": "image/png", "purpose": purpose}
                for file, size, purpose in MANIFEST_ICONS
            ],
        },
        content_type="application/manifest+json",
    )
