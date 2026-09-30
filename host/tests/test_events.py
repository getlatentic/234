# SPDX-License-Identifier: AGPL-3.0-or-later
import json

import pytest
from django.test import Client

from chat import pacing
from chat.models import Event
from chat.views import events as view
from turns import kinds

pytestmark = pytest.mark.django_db


@pytest.fixture
def stored(chat):
    for seq in range(1, 6):
        Event.objects.create(chat=chat, seq=seq, type=kinds.NOTICE, payload={"n": seq}, created_at=seq)
    return chat


def seqs(frames: list[bytes]) -> list[int]:
    return [int(f.split(b"\n")[0].removeprefix(b"id: ")) for f in frames if f.startswith(b"id: ")]


def test_the_stream_replays_from_the_cursor_in_order_without_a_gap(stored, monkeypatch):
    monkeypatch.setattr(pacing, "wait", lambda seconds: None)
    frames = list(view.follow(stored.id, 2, lifetime=0))
    assert frames == [b"retry: 1000\n\n"]
    frames = list(_follow_once(stored.id, 2))
    assert seqs(frames) == [3, 4, 5]
    assert json.loads(frames[1].split(b"data: ")[1])["payload"] == {"n": 3}


def _follow_once(chat_id, cursor):
    """One pass over the log: the generator is stopped by a clock that expires after the first poll."""
    ticks = iter([0, 0, 100, 100, 100])
    original = view.time.monotonic
    view.time.monotonic = lambda: next(ticks, 100)
    try:
        yield from view.follow(chat_id, cursor, lifetime=10)
    finally:
        view.time.monotonic = original


def test_the_cursor_is_the_later_of_since_and_last_event_id(rf):
    assert view.cursor_of(rf.get("/", {"since": "4"})) == 4
    assert view.cursor_of(rf.get("/", HTTP_LAST_EVENT_ID="9")) == 9
    assert view.cursor_of(rf.get("/", {"since": "4"}, HTTP_LAST_EVENT_ID="9")) == 9
    assert view.cursor_of(rf.get("/", {"since": "nine"})) == 0


def test_the_stream_follows_new_events_and_sends_keepalives_while_quiet(stored, monkeypatch):
    waits: list[float] = []
    clock = {"now": 0.0}
    monkeypatch.setattr(view.time, "monotonic", lambda: clock["now"])

    def wait(seconds):
        waits.append(seconds)
        clock["now"] += seconds
        if len(waits) == 3:
            Event.objects.create(chat=stored, seq=6, type=kinds.NOTICE, payload={"n": 6}, created_at=6)
        if len(waits) > 70:
            clock["now"] = 1000

    monkeypatch.setattr(pacing, "wait", wait)
    frames = list(view.follow(stored.id, 5, lifetime=40))
    assert seqs(frames) == [6]
    assert b": keepalive\n\n" in frames


def test_polling_is_quick_while_the_chat_is_busy_and_slow_when_it_is_not():
    assert pacing.poll_interval(0) == pacing.BUSY_POLL_SECONDS
    assert pacing.poll_interval(pacing.BUSY_WINDOW_SECONDS + 1) == pacing.IDLE_POLL_SECONDS


def test_only_a_member_can_open_the_stream(visitor, stored):
    stranger = Client()
    assert stranger.get(f"/c/{stored.id}/events").status_code == 404
    mine = visitor.new_chat()
    response = visitor.client.get(f"/c/{mine}/events")
    assert (
        response["Content-Type"] == "text/event-stream"
        and response["Cache-Control"] == "no-cache, no-transform"
    )
    response.close()
