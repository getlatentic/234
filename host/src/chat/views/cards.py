# SPDX-License-Identifier: AGPL-3.0-or-later
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from turns.hub import MEMORY_SERVER, HubError

from .. import card_csp, sandbox
from ..access import chat_for
from ..backend import get_backend
from .send import json_body

SCHEME_META = '<meta name="color-scheme" content="light dark">'


def with_color_scheme(markup: str) -> str:
    """A card page that follows the person's colour scheme must say so: otherwise the browser paints it an
    opaque light backdrop inside a dark chat."""
    head = markup.lower().find("<head")
    if head == -1:
        return SCHEME_META + markup
    end = markup.find(">", head) + 1
    return markup[:end] + SCHEME_META + markup[end:]


@require_GET
def card(request: HttpRequest, chat_id: str) -> JsonResponse:
    """A connector's card for the sandbox: its HTML, and what its resource asked for cut down to what the host
    grants. The page posts it to the sandbox proxy; nothing here is a document a browser opens."""
    chat_for(request, chat_id)
    server, uri = request.GET.get("server", ""), request.GET.get("uri", "")
    try:
        page = get_backend().card_page(server, uri)
    except HubError as refused:
        return JsonResponse({"error": str(refused)}, status=400)
    declaration = card_csp.resolve(page.ui, server, sandbox.origin_policy(), sandbox.granted_permissions())
    card_csp.audit(server, uri, declaration, page.ui)
    signature = sandbox.sign(f"{request.scheme}://{request.get_host()}", declaration.csp)
    if signature is None:
        return JsonResponse({"error": "The card sandbox has no signing key."}, status=503)
    response = JsonResponse(
        {
            "html": with_color_scheme(page.html),
            "csp": declaration.csp,
            "permissions": declaration.permissions,
            "prefersBorder": declaration.prefers_border,
            "sandbox": declaration.sandbox,
            "signature": signature,
            "hosts": declaration.hosts,
        }
    )
    response["Cache-Control"] = "private, max-age=300"
    return response


@require_POST
def call(request: HttpRequest, chat_id: str) -> JsonResponse:
    """A card's tools/call, relayed to the connector that served it by the chat's Durable Object."""
    chat = chat_for(request, chat_id)
    body = json_body(request)
    if body.get("server") == MEMORY_SERVER and chat.owner != request.owner:
        return JsonResponse(
            {"error": "Only the owner of this chat can change what 234 remembers."}, status=403
        )
    arguments = body.get("arguments") if isinstance(body.get("arguments"), dict) else {}
    answer = get_backend().card_call(
        chat.id, str(body.get("server", "")), str(body.get("name", "")), arguments
    )
    if "result" not in answer:
        return JsonResponse({"error": answer.get("error", "The call was refused.")}, status=403)
    return JsonResponse(answer["result"])
