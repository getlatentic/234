# SPDX-License-Identifier: AGPL-3.0-or-later
"""A connector telling the host a payment moved. The signature proves who sent it; the host then asks the
connector how the quote stands and pushes the answer to every client showing that card."""

import json

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from turns import kinds

from .. import tickets
from ..backend import get_backend
from ..models import Event

SIGNATURE_HEADER = "X-Signature"


@csrf_exempt
@require_POST
def payment(request: HttpRequest) -> HttpResponse:
    if not tickets.webhook_is_genuine(request.body, request.headers.get(SIGNATURE_HEADER, "")):
        return HttpResponse(status=401)
    try:
        quote_id = str(json.loads(request.body)["quote_id"])
    except ValueError, KeyError, TypeError:
        return HttpResponse(status=400)
    chat_id = Event.objects.filter(type=kinds.CARD, ref=quote_id).values_list("chat_id", flat=True).first()
    pushed = bool(chat_id) and get_backend().refresh_card(chat_id, quote_id)
    return JsonResponse({"pushed": pushed})
