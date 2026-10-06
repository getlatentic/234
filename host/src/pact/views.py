# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT 1.0 (Identity profile) on A2A 1.0 HTTP+JSON, under /a2a/{brandId}/. Routing comes first: an unknown
Brand or a path that is not an A2A operation is 404 or 405 with no A2A body. Then the personal-agent JWT
(401 with no body), then the operation, whose errors use the A2A envelope."""

import json
import logging
import re
import time
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from chat.backend import get_backend

from . import card
from .brands import brands
from .conversation import read, reply
from .errors import A2AError, a2a_json, error_response, no_route, rate_limited, unauthenticated
from .identity import Caller, Refused, caller_of

log = logging.getLogger(__name__)
TASK = r"[^/]+"
ROUTES: list[tuple[re.Pattern, dict[str, str]]] = [
    (re.compile(r"message:send"), {"POST": "send"}),
    (re.compile(r"message:stream"), {"POST": "unsupported"}),
    (re.compile(r"tasks"), {"GET": "list"}),
    (re.compile(rf"tasks/(?P<task>{TASK}):cancel"), {"POST": "no_task"}),
    (re.compile(rf"tasks/(?P<task>{TASK}):subscribe"), {"POST": "unsupported", "GET": "unsupported"}),
    (re.compile(rf"tasks/(?P<task>{TASK})/pushNotificationConfigs"), {"GET": "no_push", "POST": "no_push"}),
    (
        re.compile(rf"tasks/(?P<task>{TASK})/pushNotificationConfigs/[^/]+"),
        {"GET": "no_push", "DELETE": "no_push"},
    ),
    (re.compile(rf"tasks/(?P<task>{TASK})"), {"GET": "no_task"}),
    (re.compile(r"extendedAgentCard"), {"GET": "unsupported"}),
]


def _list(request: HttpRequest, *_: object) -> HttpResponse:
    raw = request.GET.get("pageSize", "50")
    if not raw.isdigit() or not 1 <= int(raw) <= 100:
        raise A2AError("INVALID_PARAMS", "pageSize is 1 to 100.")
    return a2a_json({"tasks": [], "nextPageToken": "", "pageSize": int(raw), "totalSize": 0})


def _send(request: HttpRequest, brand_id: str, caller: Caller, _: str | None) -> HttpResponse:
    if not get_backend().rate_ok(f"pact:{caller.owner}"):
        return rate_limited()
    try:
        body = json.loads(request.body or b"null")
    except ValueError as invalid:
        raise A2AError("INVALID_PARAMS", "The body is not JSON.") from invalid
    return a2a_json({"message": reply(request, brands()[brand_id], caller, read(body))})


def _no_task(request: HttpRequest, brand_id: str, caller: Caller, task: str | None) -> HttpResponse:
    raise A2AError("TASK_NOT_FOUND", f"Task not found: {task}")


def _unsupported(*_: object) -> HttpResponse:
    raise A2AError("UNSUPPORTED_OPERATION", "This operation is not supported.")


def _no_push(*_: object) -> HttpResponse:
    raise A2AError("PUSH_NOTIFICATION_NOT_SUPPORTED", "Push notifications are not supported.")


OPERATIONS: dict[str, Callable[..., HttpResponse]] = {
    "send": _send,
    "list": _list,
    "no_task": _no_task,
    "unsupported": _unsupported,
    "no_push": _no_push,
}


def _matched(rest: str) -> tuple[dict[str, str], str | None] | None:
    for pattern, methods in ROUTES:
        found = pattern.fullmatch(rest)
        if found:
            return methods, found.groupdict().get("task")
    return None


@csrf_exempt
def route(request: HttpRequest, brand_id: str, rest: str) -> HttpResponse:
    request.wants_visitor_cookie = False
    if brand_id not in brands():
        return no_route()
    if rest == ".well-known/agent-card.json":
        return _card(request, brand_id)
    matched = _matched(rest)
    if matched is None:
        return no_route()
    methods, task = matched
    if request.method not in methods:
        return no_route(tuple(methods))
    try:
        caller = caller_of(request.headers.get("Authorization", ""), settings.PACT_AUDIENCE, time.time())
    except Refused as refused:
        log.info("pact refused: %s", refused)
        return unauthenticated()
    try:
        return OPERATIONS[methods[request.method]](request, brand_id, caller, task)
    except A2AError as error:
        return error_response(error)


def _card(request: HttpRequest, brand_id: str) -> HttpResponse:
    if request.method != "GET":
        return no_route(("GET",))
    response = JsonResponse(card.document(brands()[brand_id]))
    response["Cache-Control"] = "public, max-age=300"
    return response
