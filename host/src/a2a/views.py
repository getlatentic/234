# SPDX-License-Identifier: AGPL-3.0-or-later
"""The A2A endpoint, HTTP+JSON binding: the agent card, message:send and message:stream, tasks/{id},
tasks/{id}:subscribe and tasks. It drives the same turn loop as the chat page: a message is an input to a
chat, a task is what that input made the loop do, and a stream is the chat's log read for that task."""

import json
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from chat import pacing, tickets
from chat.backend import get_backend
from chat.models import Chat, Event
from turns import fold, kinds

from . import auth, tasks, wire
from .errors import (
    A2AError,
    InvalidParams,
    InvalidRequest,
    RateLimited,
    TaskNotCancelable,
    UnsupportedOperation,
)

MAX_BODY = 16 * 1024
WAIT_SECONDS = 120
TITLE_CHARS = 60
LIST_LIMIT = 50


def card_document() -> dict[str, Any]:
    return {
        "name": "checkout-assistant",
        "description": "Pays merchants for a person through payment connectors. A payment waits for the "
        "person's own approval on a card; the agent cannot approve it.",
        "version": "0.1.0",
        "supportedInterfaces": [
            {
                "url": f"{settings.PUBLIC_BASE_URL}/a2a",
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0",
            }
        ],
        "capabilities": {"streaming": True, "pushNotifications": False, "extendedAgentCard": False},
        "securitySchemes": {"bearer": {"httpAuthSecurityScheme": {"scheme": "Bearer"}}},
        "securityRequirements": [{"schemes": {"bearer": {}}}],
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "pay-merchant",
                "name": "pay_merchant",
                "description": "Make a payment quote for a merchant. The task ends in input-required until "
                "the person approves; the status names where to send them.",
                "tags": ["payments"],
            }
        ],
    }


def a2a_endpoint(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Preflight, bearer token, version, and the protocol's error shape, around one view. The caller is not
    a browser visitor, so no visitor cookie is set."""

    @csrf_exempt
    @wraps(view)
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        request.wants_visitor_cookie = False
        if request.method == "OPTIONS":
            return auth.add_cors(request, HttpResponse(status=204))
        try:
            auth.check_version(request)
            request.principal = auth.principal_of(request)
            response = view(request, *args, **kwargs)
        except A2AError as error:
            response = JsonResponse(error.payload(), status=error.http)
            if error.http == 401:
                response["WWW-Authenticate"] = "Bearer"
        return auth.add_cors(request, response)

    return wrapped


def json_body(request: HttpRequest) -> dict[str, Any]:
    if len(request.body) > MAX_BODY:
        raise InvalidRequest("The request is too large.")
    try:
        parsed = json.loads(request.body or b"{}")
    except ValueError as invalid:
        raise InvalidRequest("The body is not JSON.") from invalid
    if not isinstance(parsed, dict):
        raise InvalidRequest("The body must be a JSON object.")
    return parsed


def handoff_for(request: HttpRequest, chat: Chat) -> str:
    return request.build_absolute_uri(reverse("chat:join", args=[tickets.mint_share_token(chat.id)]))


def chat_for_message(request: HttpRequest, message: dict[str, Any]) -> tuple[Chat, str | None]:
    """The chat a message belongs to: the context it names, the one its task lives in, or a new one."""
    owner = request.principal
    task_id = message.get("taskId") or None
    if task_id:
        task = tasks.find(str(task_id), owner)
        if fold.task_state(task.events()) in wire.FINAL:
            raise UnsupportedOperation(
                "That task has ended; start a new one by sending the message without a taskId."
            )
        asked = message.get("contextId")
        if asked and asked != task.chat.id:
            raise InvalidParams("The task belongs to another context.")
        return task.chat, task.id
    if message.get("contextId"):
        chat = Chat.objects.filter(pk=str(message["contextId"]), owner=owner).first()
        if chat is None:
            raise InvalidParams("There is no such context.")
        return chat, None
    return Chat.objects.create(owner=owner), None


def submit(request: HttpRequest) -> tasks.Task:
    """Records the caller's message as an input to its chat and returns the task it made."""
    message = json_body(request).get("message")
    text = wire.user_text(message)
    chat, task_id = chat_for_message(request, message)
    backend = get_backend()
    if not backend.rate_ok(request.principal):
        raise RateLimited("Too many messages. Wait a minute.")
    answer = backend.submit(chat.id, kinds.USER, text, task=task_id)
    if "error" in answer:
        raise InvalidParams(answer["message"])
    if not chat.title:
        chat.title = text[:TITLE_CHARS]
        chat.save(update_fields=["title"])
    return tasks.Task(answer["task"], chat)


def event_stream(generator) -> StreamingHttpResponse:
    response = StreamingHttpResponse(generator, content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    return response


def agent_card(request: HttpRequest) -> HttpResponse:
    request.wants_visitor_cookie = False
    response = JsonResponse(card_document())
    response["Cache-Control"] = "public, max-age=300"
    return auth.add_cors(request, response)


@a2a_endpoint
def message_stream(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        raise InvalidRequest("Use POST.")
    task = submit(request)
    return event_stream(tasks.follow(task, handoff_for(request, task.chat)))


@a2a_endpoint
def message_send(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        raise InvalidRequest("Use POST.")
    immediately = bool(json_body(request).get("configuration", {}).get("returnImmediately"))
    task = submit(request)
    started = last_event = time.monotonic()
    while not immediately and time.monotonic() - started < WAIT_SECONDS:
        events = task.events()
        if fold.task_state(events) in wire.STOPS_STREAM:
            break
        pacing.wait(pacing.poll_interval(time.monotonic() - last_event))
    events = task.events()
    return JsonResponse(
        {"task": wire.snapshot(task.id, task.chat.id, events, handoff_for(request, task.chat))}
    )


@a2a_endpoint
def get_task(request: HttpRequest, task_id: str) -> HttpResponse:
    task = tasks.find(task_id, request.principal)
    length = int(request.GET.get("historyLength") or 0)
    events = task.events()
    return JsonResponse(wire.snapshot(task.id, task.chat.id, events, handoff_for(request, task.chat), length))


@a2a_endpoint
def subscribe(request: HttpRequest, task_id: str) -> HttpResponse:
    task = tasks.find(task_id, request.principal)
    if fold.task_state(task.events()) in wire.FINAL:
        raise UnsupportedOperation("That task has ended.")
    return event_stream(tasks.follow(task, handoff_for(request, task.chat)))


@a2a_endpoint
def cancel(request: HttpRequest, task_id: str) -> HttpResponse:
    tasks.find(task_id, request.principal)
    raise TaskNotCancelable("A turn cannot be stopped once it has started.")


@a2a_endpoint
def list_tasks(request: HttpRequest) -> HttpResponse:
    chats = Chat.objects.filter(owner=request.principal)
    if context := request.GET.get("contextId"):
        chats = chats.filter(pk=context)
    found: dict[str, Chat] = {}
    rows = Event.objects.filter(chat__in=chats, type=kinds.USER).exclude(task="").order_by("-seq")
    for row in rows.select_related("chat")[: LIST_LIMIT * 4]:
        found.setdefault(row.task, row.chat)
    listed = []
    for task_id, chat in list(found.items())[:LIST_LIMIT]:
        events = tasks.Task(task_id, chat).events()
        listed.append(wire.snapshot(task_id, chat.id, events, handoff_for(request, chat)))
    return JsonResponse(
        {"tasks": listed, "nextPageToken": "", "pageSize": len(listed), "totalSize": len(found)}
    )
