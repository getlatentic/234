# SPDX-License-Identifier: AGPL-3.0-or-later
"""The empty home as a static page. It is rendered once, at build time, from the chat template with nothing
that belongs to a visitor in it (what the deployment decides, such as whether sign-in is offered, is in it),
and Workers static assets serve it without starting the Worker. What a visitor adds (the CSRF token, who they
are, their chats) arrives from `/api/me` (views/me.py) and is filled in by the page's script."""

from django.conf import settings
from django.http import HttpRequest
from django.template.loader import render_to_string

from .models import Chat
from .security import page_headers
from .starters import STARTERS

# The chat id the shell is rendered with: the page replaces it, in every address that holds it, by an id
# of its own (static/chat/shell.js).
PLACEHOLDER_CHAT = "0" * 32
# Short, so a deploy reaches visitors within a minute; the files the page loads revalidate.
CACHE_CONTROL = "public, max-age=60, must-revalidate"


def render_shell(request: HttpRequest | None = None) -> str:
    if request is None:
        from django.test import RequestFactory  # the build has no request; the Worker never imports this

        request = RequestFactory().get("/")
    return render_to_string(
        "chat/chat.html",
        {
            "shell": True,
            "chat": Chat(id=PLACEHOLDER_CHAT),
            "draft": True,
            "items": [],
            "last_seq": 0,
            "working": False,
            "chats": [],
            "starters": STARTERS,
            "model_problem": None,
            "transport": "",
            "csrf_token": "",
            "account": None,
            "sign_in_enabled": settings.SIGN_IN_ENABLED,
        },
        request=request,
    )


def headers_file() -> str:
    """The shell's `_headers` file (Workers static assets): the page's security headers and its caching."""
    rules = {**page_headers(), "Cache-Control": CACHE_CONTROL}
    lines = [f"  {name}: {value}" for name, value in rules.items()]
    return "\n".join(["/", *lines, ""])


def write_shell() -> list[str]:
    """Writes index.html and _headers next to the collected static files; returns their paths."""
    root = settings.STATIC_ROOT.parent
    root.mkdir(parents=True, exist_ok=True)
    written = {"index.html": render_shell(), "_headers": headers_file()}
    for name, text in written.items():
        (root / name).write_text(text, encoding="utf-8")
    return [str(root / name) for name in written]
