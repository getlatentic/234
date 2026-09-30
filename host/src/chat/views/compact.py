# SPDX-License-Identifier: AGPL-3.0-or-later
"""Summarising the older part of a chat on request: the owner's own control, for trying compaction out."""

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from ..access import chat_for
from ..backend import get_backend
from .send import json_body


def _keep_of(request: HttpRequest) -> int | None:
    keep = json_body(request).get("keep_recent_tokens")
    return keep if isinstance(keep, int) and not isinstance(keep, bool) and keep >= 0 else None


@require_POST
def compact(request: HttpRequest, chat_id: str) -> HttpResponse:
    """Compacts the chat now, whatever its size; only its owner may. The body may name `keep_recent_tokens`,
    how much of the end of the conversation stays word for word. `compacted` is false when there was nothing
    to cover."""
    chat = chat_for(request, chat_id)
    if chat.owner != request.owner:
        return HttpResponse(status=403)
    backend = get_backend()
    if not backend.rate_ok(f"compact:{request.owner}"):
        return JsonResponse(
            {"error": "rate_limited", "message": "Too many requests. Wait a minute."}, status=429
        )
    return JsonResponse(backend.compact(chat.id, _keep_of(request)))
