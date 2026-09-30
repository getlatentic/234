# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio

import httpx
import pytest

from turns import kinds
from turns.budget import GLOBAL_SCOPE, day_of
from turns.eventlog import EventLog
from turns.hub import HubError
from turns.model import ModelError
from turns.runner import BAD_ARGUMENTS, UNREACHABLE, TurnRunner
from turns.settings import Settings

from .support import FakeHub, ScriptedModel, quote_result, tool_call

MAKE = "s__make"


def settings(**changes) -> Settings:
    return Settings(mcp_url="http://x", llm_base_url="http://m", llm_api_key="k", **changes)


class Rig:
    def __init__(self, chat, sql, clock, model, hub, **changes):
        self.log = EventLog(sql, chat.id, clock)
        counter = iter(range(1, 1000))
        self.runner = TurnRunner(
            self.log, sql, model, hub, settings(**changes), "v:a", clock, ids=lambda: f"id{next(counter)}"
        )

    async def say(self, text="pay", **fields):
        return await self.log.append(kinds.USER, {"text": text}, **fields)

    async def types(self):
        return [e.type for e in await self.log.read()]

    async def of(self, type):
        return [e for e in await self.log.read() if e.type == type]


@pytest.fixture
def rig(chat, sql, clock):
    def make(model, hub=None, **changes):
        return Rig(chat, sql, clock, model, hub or FakeHub({MAKE: quote_result()}), **changes)

    return make


async def test_a_plain_reply_streams_then_finishes_the_turn(rig):
    r = rig(ScriptedModel("Hello there"))
    await r.say("hi")
    await r.runner.run()
    assert await r.types() == ["user", "turn.started", "text", "assistant", "turn.finished"]
    reply = (await r.of("assistant"))[0]
    assert reply.payload["text"] == "Hello there " and reply.payload["finish_reason"] == "stop"
    finished = (await r.of("turn.finished"))[0]
    assert finished.payload == {"task": "id1", "reason": "completed", "finish_reasons": ["stop"], "rounds": 1}
    assert {e.task for e in await r.log.read() if e.type != "user"} == {"id1"}


async def test_text_is_flushed_in_pieces_no_faster_than_the_flush_interval(rig, clock):
    class Slow(ScriptedModel):
        async def stream(self, messages, tools):
            async for piece in super().stream(messages, tools):
                clock.advance(0.1)
                yield piece

    r = rig(Slow("a b c d e f"), flush_seconds=0.25)
    await r.say()
    await r.runner.run()
    pieces = [e.payload["text"] for e in await r.of("text")]
    assert "".join(pieces) == "a b c d e f " and 1 < len(pieces) < 6


async def test_a_tool_call_makes_a_card_and_the_turn_waits_for_the_person(rig):
    model = ScriptedModel(("", [tool_call(MAKE, {"amount": 1})]), "Please check the card.")
    r = rig(model)
    await r.say("pay 1")
    await r.runner.run()
    assert await r.types() == [
        "user", "turn.started", "assistant", "tool", "card", "text", "assistant", "turn.finished",
    ]  # fmt: skip
    card = (await r.of("card"))[0]
    assert card.ref == "qt-1" and card.payload["result"]["_meta"]["approvalToken"] == "tok-secret"
    assert (await r.of("turn.finished"))[0].payload["reason"] == "input_required"
    assert "tok-secret" not in str(model.sent)


async def test_a_settled_card_lets_the_turn_complete(rig):
    hub = FakeHub({MAKE: quote_result("succeeded")})
    r = rig(ScriptedModel(("", [tool_call(MAKE, {})]), "Done."), hub)
    await r.say()
    await r.runner.run()
    assert (await r.of("turn.finished"))[0].payload["reason"] == "completed"


async def test_arguments_with_a_real_newline_inside_a_string_are_read(rig):
    r = rig(ScriptedModel(("", [tool_call(MAKE, '{"note": "line one\nline two"}')]), "Done."))
    await r.say()
    await r.runner.run()
    tool = (await r.of("tool"))[0]
    assert not tool.payload["is_error"] and tool.payload["arguments"] == {"note": "line one\nline two"}


async def test_arguments_that_are_not_json_come_back_as_a_refused_tool_call(rig):
    r = rig(ScriptedModel(("", [tool_call(MAKE, "{oops")]), "Sorry."))
    await r.say()
    await r.runner.run()
    tool = (await r.of("tool"))[0]
    assert tool.payload["is_error"] and tool.payload["result_text"] == BAD_ARGUMENTS
    assert (await r.of("turn.finished"))[0].payload["reason"] == "completed"


@pytest.mark.parametrize("failure", [HubError("x"), httpx.ConnectError("down")])
async def test_an_unreachable_connector_is_a_tool_error_the_model_can_report(rig, failure):
    r = rig(ScriptedModel(("", [tool_call(MAKE, {})]), "I could not do that."), FakeHub({MAKE: failure}))
    await r.say()
    await r.runner.run()
    assert (await r.of("tool"))[0].payload["result_text"] == UNREACHABLE
    assert not await r.of("card")


async def test_a_model_that_fails_ends_the_turn_as_failed_and_is_not_asked_again(rig):
    model = ScriptedModel(("partial", ModelError("The model endpoint answered HTTP 500.")))
    r = rig(model)
    await r.say()
    await r.runner.run()
    notice = (await r.of("notice"))[0]
    assert notice.payload == {"level": "error", "text": "The model endpoint answered HTTP 500."}
    assert (await r.of("assistant"))[0].payload["finish_reason"] == "error"
    assert (await r.of("turn.finished"))[0].payload["reason"] == "failed"
    assert len(model.sent) == 1


async def test_a_reply_cut_short_says_so(rig):
    class Cut(ScriptedModel):
        async def stream(self, messages, tools):
            from turns.model import Finished, TextDelta

            yield TextDelta("half")
            yield Finished("length", [])

    r = rig(Cut())
    await r.say()
    await r.runner.run()
    assert "ran out of room" in (await r.of("notice"))[0].payload["text"]
    assert (await r.of("turn.finished"))[0].payload["finish_reasons"] == ["length"]


async def test_the_turn_stops_after_too_many_rounds(rig):
    calls = [("", [tool_call(MAKE, {}, f"c{n}")]) for n in range(5)]
    r = rig(ScriptedModel(*calls), max_tool_rounds=2)
    await r.say()
    await r.runner.run()
    finished = (await r.of("turn.finished"))[0].payload
    assert finished["reason"] == kinds.MAX_ROUNDS and finished["rounds"] == 2
    assert "too many tool calls" in (await r.of("notice"))[0].payload["text"]


async def test_a_message_sent_while_the_model_streams_is_answered_in_the_same_turn(rig):
    class Interrupted(ScriptedModel):
        async def stream(self, messages, tools):
            if not self.sent:
                await r.say("actually make it two")
            async for piece in super().stream(messages, tools):
                yield piece

    model = Interrupted("first answer", "second answer")
    r = rig(model)
    await r.say("make it one")
    await r.runner.run()
    assert [m["content"] for m in model.sent[1][1:]] == [
        "make it one",
        "first answer ",
        "actually make it two",
    ]
    assert [e.payload["text"] for e in await r.of("assistant")] == ["first answer ", "second answer "]
    assert len(await r.of("turn.started")) == 1 and len(await r.of("turn.finished")) == 1


async def test_a_card_note_is_kept_for_the_model_and_does_not_start_a_turn(rig):
    model = ScriptedModel("Hello", "Your payment went through.")
    r = rig(model)
    await r.say()
    await r.runner.run()
    await r.log.append(kinds.CARD_CONTEXT, {"text": "The card now shows: paid."})
    await r.runner.run()
    assert len(model.sent) == 1
    await r.say("did it work?")
    await r.runner.run()
    assert any(m["content"] == "[card update] The card now shows: paid." for m in model.sent[1])


async def test_a_card_message_continues_the_task_that_was_waiting_for_the_person(rig):
    r = rig(ScriptedModel(("", [tool_call(MAKE, {})]), "Check the card.", "Payment received."))
    await r.say()
    await r.runner.run()
    waiting = (await r.of("turn.finished"))[0].payload["task"]
    from turns import fold

    task = fold.waiting_task(await r.log.context())
    assert task == waiting
    await r.log.append(kinds.CARD_MESSAGE, {"text": "paid"}, task=task)
    await r.runner.run()
    assert {e.task for e in await r.of("turn.started")} == {waiting}
    assert len(await r.of("turn.started")) == 2


async def test_the_daily_caps_stop_a_round_before_the_model_is_called(rig, sql, clock):
    model = ScriptedModel("never")
    r = rig(model, model_calls_per_day=1)
    await sql.execute(
        "INSERT INTO chat_budget (scope, day, used) VALUES (?, ?, 1)", GLOBAL_SCOPE, day_of(clock())
    )
    await r.say()
    await r.runner.run()
    assert model.sent == []
    assert "budget is used up" in (await r.of("notice"))[0].payload["text"]
    assert (await r.of("turn.finished"))[0].payload["reason"] == "failed"


async def test_the_visitor_cap_is_counted_per_visitor(rig, sql):
    model = ScriptedModel("one", "two")
    r = rig(model, visitor_model_calls_per_day=1)
    await r.say()
    await r.runner.run()
    await r.say("again")
    await r.runner.run()
    assert len(model.sent) == 1
    assert "today's share" in (await r.of("notice"))[0].payload["text"]


async def test_running_again_when_there_is_nothing_to_do_changes_nothing(rig):
    r = rig(ScriptedModel("Hi"))
    await r.say()
    await r.runner.run()
    before = await r.log.last_seq()
    await r.runner.run()
    assert await r.log.last_seq() == before


class Runaway(ScriptedModel):
    """A model that sends its reasoning and never finishes: the stream stays open and says nothing."""

    async def stream(self, messages, tools):
        self.sent.append(messages)
        await asyncio.sleep(3600)
        yield None


async def test_a_model_that_never_finishes_ends_the_turn_as_failed_when_the_round_deadline_passes(rig):
    from turns.runner import TOO_SLOW

    r = rig(Runaway(), round_deadline_seconds=0.05)
    await r.say("hi")
    await r.runner.run()
    assert (await r.of("notice"))[0].payload == {"level": "error", "text": TOO_SLOW}
    assert (await r.of("assistant"))[0].payload["finish_reason"] == "error"
    assert (await r.of("turn.finished"))[0].payload["reason"] == "failed"
