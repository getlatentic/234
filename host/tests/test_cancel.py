# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stopping a turn: what was said stays, nothing runs again, and only later messages are answered."""

import asyncio

import pytest

from a2a import wire
from turns import fold, kinds
from turns.chat_core import ChatCore
from turns.eventlog import Event
from turns.model import Finished
from turns.settings import Settings

from .support import FakeAlarms, FakeHub, FakeSockets, ScriptedModel, quote_result, tool_call

MAKE = "s__make"


class Gated(ScriptedModel):
    """Says its words, then holds the stream open until the test lets go."""

    def __init__(self, *script):
        super().__init__(*script)
        self.gate = asyncio.Event()

    async def stream(self, messages, tools):
        held = not self.sent
        async for piece in super().stream(messages, tools):
            if held and isinstance(piece, Finished):
                await self.gate.wait()
            yield piece


class GatedHub(FakeHub):
    def __init__(self):
        super().__init__({MAKE: quote_result()})
        self.gate = asyncio.Event()

    async def call_model_tool(self, qualified, arguments, owner, key):
        self.calls.append((qualified, arguments))
        await self.gate.wait()
        raise AssertionError("the tool was let through")


@pytest.fixture
def make(chat, sql, clock):
    def build(model, hub=None):
        alarms = FakeAlarms()
        settings = Settings(mcp_url="x", llm_base_url="m", llm_api_key="k", flush_seconds=0)
        core = ChatCore(
            chat.id,
            sql,
            settings,
            model,
            hub or FakeHub({MAKE: quote_result()}),
            FakeSockets(),
            alarms,
            clock,
        )
        return core, alarms

    return build


async def events(core, *types):
    return [e for e in await core.log.read() if not types or e.type in types]


async def until(core, type):
    while not await events(core, type):
        await asyncio.sleep(0)


async def settle(core):
    while core.running:
        await asyncio.gather(core._driver, return_exceptions=True)


async def test_stopping_a_reply_keeps_what_was_said_and_ends_the_turn(make):
    model = Gated("one two three", "a fresh answer")
    core, alarms = make(model)
    await core.submit(kinds.USER, "hi")
    await until(core, kinds.TEXT)
    assert await core.cancel() == {"cancelled": True}
    [reply] = await events(core, kinds.ASSISTANT)
    assert reply.payload["text"] == "one two three " and reply.payload["finish_reason"] == "cancelled"
    [finished] = await events(core, kinds.TURN_FINISHED)
    assert finished.payload["reason"] == "cancelled" and finished.payload["upto"] >= reply.seq - 1
    assert not core.running and alarms.at is None
    assert len(model.sent) == 1


async def test_a_stopped_reply_is_part_of_what_the_model_is_told_next(make):
    model = Gated("one two", "and on")
    core, _ = make(model)
    await core.submit(kinds.USER, "hi")
    await until(core, kinds.TEXT)
    await core.cancel()
    await core.submit(kinds.USER, "go on")
    await settle(core)
    told = [m["content"] for m in model.sent[1] if m["role"] in ("user", "assistant")]
    assert told == ["hi", "one two ", "go on"]
    assert [e.payload["reason"] for e in await events(core, kinds.TURN_FINISHED)] == [
        "cancelled",
        "completed",
    ]


async def test_stopping_before_the_model_has_said_anything_leaves_no_reply(make):
    class Silent(Gated):
        async def stream(self, messages, tools):
            await self.gate.wait()
            yield Finished("stop", [])

    model = Silent()
    core, _ = make(model)
    await core.submit(kinds.USER, "hi")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await core.cancel()
    [reply] = await events(core, kinds.ASSISTANT)
    assert reply.payload["text"] == "" and reply.payload["finish_reason"] == "cancelled"
    assert [e.payload["reason"] for e in await events(core, kinds.TURN_FINISHED)] == ["cancelled"]


async def test_stopping_the_moment_a_message_is_sent_answers_nothing(make):
    model = ScriptedModel("never said")
    core, _ = make(model)
    await core.submit(kinds.USER, "hi")
    assert await core.cancel() == {"cancelled": True}
    await asyncio.sleep(0)
    assert model.sent == [] and not core.running
    assert [e.type for e in await events(core)] == ["user", "turn.started", "turn.finished"]


async def test_a_tool_call_that_is_stopped_is_answered_as_stopped_and_never_run_again(make):
    hub = GatedHub()
    model = ScriptedModel(("", [tool_call(MAKE, {"amount": 1})]), "must not be asked")
    core, _ = make(model, hub)
    await core.submit(kinds.USER, "pay 1")
    while not hub.calls:
        await asyncio.sleep(0)
    assert await core.cancel() == {"cancelled": True}
    await asyncio.sleep(0)
    [tool] = await events(core, kinds.TOOL)
    assert tool.payload["cancelled"] and tool.payload["is_error"] and "Stopped" in tool.payload["result_text"]
    assert not await events(core, kinds.CARD)
    assert len(hub.calls) == 1 and len(model.sent) == 1 and not core.running
    assert fold.next_action(await core.log.context()) == fold.Idle()


async def test_what_was_sent_before_the_stop_is_settled_and_what_comes_after_is_answered(make):
    model = Gated("first", "second")
    core, _ = make(model)
    await core.submit(kinds.USER, "one")
    await until(core, kinds.TEXT)
    await core.submit(kinds.USER, "two, sent while it was answering")
    await core.cancel()
    await asyncio.sleep(0)
    assert len(model.sent) == 1
    await core.submit(kinds.USER, "three, after the stop")
    await settle(core)
    told = [m["content"] for m in model.sent[1] if m["role"] == "user"]
    assert told[-1] == "three, after the stop" and len(model.sent) == 2


async def test_stopping_when_nothing_runs_changes_nothing(make):
    core, _ = make(ScriptedModel("done"))
    assert await core.cancel() == {"cancelled": False}
    await core.submit(kinds.USER, "hi")
    await settle(core)
    before = len(await events(core))
    assert await core.cancel() == {"cancelled": False} and len(await events(core)) == before


async def test_a_turn_stopped_from_another_instance_after_a_restart_drops_its_half_reply(make):
    core, _ = make(ScriptedModel("x"))
    log = core.log
    await log.append(kinds.USER, {"text": "hi"}, task="t1")
    await log.append(kinds.TURN_STARTED, {"task": "t1", "trigger": 1}, task="t1")
    await log.append(kinds.TEXT, {"message": "m1", "text": "Let me"}, task="t1")
    assert await core.cancel() == {"cancelled": True}
    types = [e.type for e in await events(core)]
    assert types[-2:] == ["round.aborted", "turn.finished"]
    assert fold.next_action(await core.log.context()) == fold.Idle()


def test_a_stopped_task_is_canceled_and_final_for_a_caller():
    def event(seq, type, payload, task="t"):
        return Event(seq, type, task, None, payload, 1_790_000_000_000)

    log = [
        event(1, kinds.USER, {"text": "hi"}),
        event(2, kinds.TURN_STARTED, {"task": "t"}),
        event(3, kinds.TURN_FINISHED, {"task": "t", "reason": kinds.CANCELLED, "upto": 2}),
    ]
    assert fold.task_state(log) == "canceled"
    body = wire.snapshot("t", "c", log, "http://x/join")
    assert body["status"]["state"] == "TASK_STATE_CANCELED" and "canceled" in wire.FINAL


@pytest.mark.django_db
def test_the_cancel_endpoint_stops_the_visitors_own_chat_only(visitor, backend):
    mine = visitor.new_chat()
    answer = visitor.post(f"/c/{mine}/cancel")
    assert answer.status_code == 200 and answer.json() == {"cancelled": True}
    assert backend.cancelled == [mine]
    assert visitor.client.get(f"/c/{mine}/cancel").status_code == 405


@pytest.mark.django_db
def test_someone_elses_chat_cannot_be_stopped(visitor, backend, other_chat):
    assert visitor.post(f"/c/{other_chat.id}/cancel").status_code == 404
    assert backend.cancelled == []
