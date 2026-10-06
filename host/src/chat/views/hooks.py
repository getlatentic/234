# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /hooks/events: the MCP events the connectors send for quotes this host subscribed to
(turns/quote_events.py). The signature is the host's own key; a verification is answered with its challenge,
and a quote.finished reaches the chat that holds the quote's card. An event for a chat that is gone answers
410, which ends the subscription."""

import json
import time

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from turns import kinds, quote_events

from ..backend import get_backend
from ..models import Event

MAX_BODY = 256 * 1024


def _read(request: HttpRequest) -> dict | None:
    try:
        body = json.loads(request.body)
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


@csrf_exempt
@require_POST
def events(request: HttpRequest) -> HttpResponse:
    if not settings.EVENTS_SECRET:
        raise Http404
    if len(request.body) > MAX_BODY:
        return HttpResponse(status=413)
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not quote_events.genuine(settings.EVENTS_SECRET, headers, request.body, time.time()):
        return HttpResponse(status=401)
    body = _read(request)
    if body is None:
        return HttpResponse(status=400)
    if body.get("type") == "verification":
        return JsonResponse({"challenge": body.get("challenge")})
    data = body.get("data") or {}
    if body.get("name") != quote_events.EVENT or not isinstance(data, dict) or not data.get("quote_id"):
        return HttpResponse(status=204)
    quote_id = str(data["quote_id"])
    chat_id = Event.objects.filter(type=kinds.CARD, ref=quote_id).values_list("chat_id", flat=True).first()
    if chat_id is None:
        return HttpResponse(status=410)
    told = get_backend().quote_ended(chat_id, quote_id, str(body.get("eventId", "")), quote_events.told(data))
    return JsonResponse({"told": told})
