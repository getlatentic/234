# SPDX-License-Identifier: AGPL-3.0-or-later
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from .. import tickets
from ..access import chat_for


@require_POST
def ticket(request: HttpRequest, chat_id: str) -> JsonResponse:
    """A one-minute ticket for the WebSocket. The upgrade is answered before Django, from the ticket alone,
    so ownership is checked here, once, where the chat is looked up."""
    chat = chat_for(request, chat_id)
    path = reverse("chat:socket", args=[chat.id])
    return JsonResponse({"path": f"{path}?ticket={tickets.mint_ws_ticket(chat.id)}"})


def upgrade_required(request: HttpRequest, chat_id: str) -> HttpResponse:
    """The socket path is answered by the Worker before Django; a plain request to it lands here."""
    return HttpResponse("This address is for a WebSocket.", status=426, headers={"Upgrade": "websocket"})
