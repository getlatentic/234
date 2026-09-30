# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compacting on request: the chat's object, the view that asks for it, and who may ask."""

import asyncio

import pytest

from chat import tickets
from chat.models import Chat
from turns import kinds
from turns.chat_core import ChatCore
from turns.settings import Settings

from .compaction_support import Rig, RoutedModel
from .support import FakeAlarms, FakeHub, FakeSockets


@pytest.fixture
def make(chat, sql, clock):
    def build(model=None, **changes):
        settings = Settings(mcp_url="x", llm_base_url="m", llm_api_key="k", keep_recent_tokens=300, **changes)
        return ChatCore(
            chat.id, sql, settings, model or RoutedModel(), FakeHub(), FakeSockets(), FakeAlarms(), clock
        )

    return build


async def seed(core: ChatCore, turns: int = 14) -> None:
    rig = Rig.__new__(Rig)
    rig.log = core.log
    await Rig.chat(rig, turns)


async def test_the_owner_can_compact_a_chat_whatever_its_size(make):
    core = make()
    await seed(core)
    answer = await core.compact(100)
    assert (
        answer["compacted"]
        and answer["trigger"] == "manual"
        and answer["tokens"]["after"] < answer["tokens"]["before"]
    )
    assert [e.type for e in await core.log.read(limit=1000)].count(kinds.COMPACTION) == 1


async def test_nothing_to_cover_is_said_so(make):
    core = make()
    assert await core.compact() == {"compacted": False}


async def test_requests_that_arrive_together_make_one_compaction_and_the_same_answer(make):
    core = make(RoutedModel(slow=0.02))
    await seed(core)
    first, second, third = await asyncio.gather(core.compact(100), core.compact(100), core.compact(100))
    assert first["compacted"] and first == second == third
    assert [e.type for e in await core.log.read(limit=1000)].count(kinds.COMPACTION) == 1


async def test_a_compaction_during_a_turn_and_the_persons_own_do_not_make_two(make):
    core = make(RoutedModel(slow=0.02), context_window_tokens=2000, compact_at=0.5)
    await seed(core)
    asking = asyncio.ensure_future(core.compact(100))
    await core.submit(kinds.USER, "what now?")
    await asking
    while core.running:
        await asyncio.sleep(0.01)
    types = [e.type for e in await core.log.read(limit=1000)]
    assert types.count(kinds.COMPACTION) == 1 and types[-1] == kinds.TURN_FINISHED


async def test_a_chat_that_is_deleted_is_not_compacted(make):
    core = make(RoutedModel(slow=0.05))
    await seed(core)
    asking = asyncio.ensure_future(core.compact(100))
    await asyncio.sleep(0.01)
    await core.purge()
    assert (await asking)["compacted"] is False
    assert await core.log.read(limit=1000) == []
    assert await core.compact(100) == {"compacted": False}


@pytest.mark.django_db
def test_the_owner_asks_for_a_compaction_and_gets_the_answer(visitor, backend):
    chat_id = visitor.new_chat()
    answer = visitor.post(f"/c/{chat_id}/compact")
    assert answer.status_code == 200 and answer.json()["compacted"] is True
    assert backend.compacted == [(chat_id, None)]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("body", "keep"),
    [({"keep_recent_tokens": 50}, 50), ({"keep_recent_tokens": 0}, 0), ({"keep_recent_tokens": -1}, None),
     ({"keep_recent_tokens": "9"}, None), ({"keep_recent_tokens": True}, None), ({}, None)],
)  # fmt: skip
def test_how_much_stays_verbatim_can_be_named_and_nothing_else_is_taken_from_the_body(
    visitor, backend, body, keep
):
    chat_id = visitor.new_chat()
    visitor.post(f"/c/{chat_id}/compact", json=body)
    assert backend.compacted == [(chat_id, keep)]


@pytest.mark.django_db
def test_a_guest_with_the_share_link_may_read_a_chat_but_not_compact_it(visitor, backend, client):
    chat_id = visitor.new_chat()
    from django.test import Client

    guest = Client()
    page = guest.get("/")
    token = page.content.decode().split('csrf-token" content="')[1].split('"')[0]
    guest.get(f"/join/{tickets.mint_share_token(chat_id)}")
    answer = guest.post(f"/c/{chat_id}/compact", HTTP_X_CSRFTOKEN=token)
    assert answer.status_code == 403 and backend.compacted == []
    assert Chat.objects.get(pk=chat_id)


@pytest.mark.django_db
def test_a_stranger_cannot_compact_someone_elses_chat(visitor, backend):
    from django.test import Client

    chat_id = visitor.new_chat()
    stranger = Client()
    page = stranger.get("/")
    token = page.content.decode().split('csrf-token" content="')[1].split('"')[0]
    assert stranger.post(f"/c/{chat_id}/compact", HTTP_X_CSRFTOKEN=token).status_code == 404
    assert backend.compacted == []


@pytest.mark.django_db
def test_a_visitor_over_the_rate_limit_is_told_to_wait(visitor, backend):
    chat_id = visitor.new_chat()
    backend.allow = False
    answer = visitor.post(f"/c/{chat_id}/compact")
    assert answer.status_code == 429 and backend.compacted == []


@pytest.mark.django_db
def test_a_compaction_needs_the_csrf_token(visitor, backend, client):
    from django.test import Client

    chat_id = visitor.new_chat()
    strict = Client(enforce_csrf_checks=True)
    strict.cookies.update(client.cookies)
    assert strict.post(f"/c/{chat_id}/compact").status_code == 403 and backend.compacted == []


@pytest.mark.django_db
def test_the_page_marks_only_the_latest_compaction_with_one_quiet_line_and_keeps_every_message(visitor):
    from chat.models import Event

    chat_id = visitor.new_chat()
    for seq, (type, payload) in enumerate(
        [
            (kinds.USER, {"text": "one"}),
            (
                kinds.COMPACTION,
                {"trigger": "auto", "summary": "FIRST SUMMARY", "covers": {"first": 1, "last": 1}},
            ),
            (kinds.USER, {"text": "two"}),
            (
                kinds.COMPACTION,
                {"trigger": "auto", "summary": "SECOND SUMMARY", "covers": {"first": 2, "last": 3}},
            ),
            (kinds.USER, {"text": "three"}),
        ],
        start=1,
    ):
        Event.objects.create(chat_id=chat_id, seq=seq, type=type, payload=payload, created_at=0)
    page = visitor.client.get(f"/c/{chat_id}/").content.decode()
    body = page.split('data-slot="thread"')[1].split("<chat-composer")[0]
    assert body.count("Earlier messages were summarised") == 1
    assert "SECOND SUMMARY" in body and "FIRST SUMMARY" not in page
    assert all(word in body for word in ("one", "two", "three"))
    assert '<template data-kind="compaction">' in page
