# SPDX-License-Identifier: AGPL-3.0-or-later
"""The log as server-sent events: replay from a cursor, then follow. The fallback to the WebSocket, and
the same log every other reader uses. It polls D1; the Durable Object's socket is the push path."""

import json
import time
from collections.abc import Iterator

from django.http import HttpRequest, StreamingHttpResponse
from django.views.decorators.http import require_GET

from .. import pacing
from ..access import chat_for
from ..models import Event

BATCH = 100
LIFETIME_SECONDS = 55
KEEPALIVE_SECONDS = 15


def cursor_of(request: HttpRequest) -> int:
    """Where to resume: the later of `since` and the browser's own Last-Event-ID."""
    values = [request.GET.get("since"), request.headers.get("Last-Event-ID")]
    return max([int(v) for v in values if v and v.isdigit()] or [0])


def frame(event: Event) -> bytes:
    body = json.dumps(event.as_logged().wire(), ensure_ascii=False)
    return f"id: {event.seq}\ndata: {body}\n\n".encode()


def follow(chat_id: str, cursor: int, lifetime: float = LIFETIME_SECONDS) -> Iterator[bytes]:
    started = last_event = last_sent = time.monotonic()
    yield b"retry: 1000\n\n"
    while time.monotonic() - started < lifetime:
        events = list(Event.objects.filter(chat_id=chat_id, seq__gt=cursor)[:BATCH])
        for event in events:
            cursor = event.seq
            yield frame(event)
        if events:
            last_event = last_sent = time.monotonic()
            continue
        if time.monotonic() - last_sent > KEEPALIVE_SECONDS:
            last_sent = time.monotonic()
            yield b": keepalive\n\n"
        pacing.wait(pacing.poll_interval(time.monotonic() - last_event))


@require_GET
def events(request: HttpRequest, chat_id: str) -> StreamingHttpResponse:
    chat = chat_for(request, chat_id)
    response = StreamingHttpResponse(follow(chat.id, cursor_of(request)), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    return response
