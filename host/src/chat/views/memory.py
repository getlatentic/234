# SPDX-License-Identifier: AGPL-3.0-or-later
"""The person's own view of what 234 remembers, in the chats drawer: the list, a title or a hook changed in
place, a note forgotten (with an Undo), a copy to keep, and everything deleted. Only a signed-in account has
any of it: for anyone else every address here is a 404, so the page says nothing. The notes are read and
changed by the memory connector for the account's own key; nothing here chooses an owner."""

import json
from typing import Any

import httpx
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from turns.hub import HubError

from ..backend import get_backend
from .send import json_body

UNREACHABLE = "Memory could not be reached. Try again."
EXPORT_NAME = "234-memory.json"


def _plain(text: str) -> str:
    head, _, rest = text.partition(": ")
    return rest if head.isupper() or head.replace("_", "").isupper() else text


def _ask(request: HttpRequest, tool: str, arguments: dict[str, Any] | None = None) -> JsonResponse:
    account = getattr(request, "account", None)
    if account is None:
        raise Http404
    try:
        result = get_backend().memory(account.owner, tool, arguments or {})
    except HubError, httpx.HTTPError:
        return JsonResponse({"error": UNREACHABLE}, status=502)
    if result.get("isError"):
        text = next((b.get("text", "") for b in result.get("content", []) if b.get("type") == "text"), "")
        return JsonResponse({"error": _plain(text) or "The request was refused."}, status=400)
    return JsonResponse(result.get("structuredContent") or {})


@require_GET
def entries(request: HttpRequest) -> JsonResponse:
    return _ask(request, "list_memories")


@require_POST
def edit(request: HttpRequest, entry_id: str) -> JsonResponse:
    body = json_body(request)
    fields = {k: body[k] for k in ("title", "hook") if isinstance(body.get(k), str)}
    return _ask(request, "edit_memory", {"id": entry_id, **fields})


@require_POST
def forget(request: HttpRequest, entry_id: str) -> JsonResponse:
    return _ask(request, "forget_memory", {"id": entry_id})


@require_POST
def undo(request: HttpRequest) -> JsonResponse:
    body = json_body(request)
    arguments = {"proposal_id": str(body.get("proposal_id", "")), "confirm_token": str(body.get("token", ""))}
    return _ask(request, "undo_memory", arguments)


@require_GET
def export(request: HttpRequest) -> HttpResponse:
    answer = _ask(request, "export_memories")
    if answer.status_code != 200:
        return answer
    response = HttpResponse(
        json.dumps(json.loads(answer.content), indent=2, ensure_ascii=False), content_type="application/json"
    )
    response["Content-Disposition"] = f'attachment; filename="{EXPORT_NAME}"'
    response["Cache-Control"] = "no-store"
    return response


@require_POST
def delete_everything(request: HttpRequest) -> JsonResponse:
    return _ask(request, "delete_all_memories")
