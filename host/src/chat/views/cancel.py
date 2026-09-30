# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stopping a reply: the person's own control over the turn that is answering them."""

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from ..access import chat_for
from ..backend import get_backend


@require_POST
def cancel(request: HttpRequest, chat_id: str) -> JsonResponse:
    """Stops the chat's running turn and keeps its reply so far; `cancelled` is false if none was running."""
    chat = chat_for(request, chat_id)
    return JsonResponse(get_backend().cancel(chat.id))
