# SPDX-License-Identifier: AGPL-3.0-or-later
"""A turn that cannot get anywhere ends, and a tool call never runs twice by accident: every connector call
has a deadline, is marked `tool.started` before it leaves, and after a restart runs again only when that is
safe. Resumes count only while nothing moves, and a watchdog that keeps finding nothing changed stops."""

import asyncio

import pytest

from turns import kinds
from turns.chat_core import ChatCore
from turns.settings import Settings

from .support import FakeAlarms, FakeHub, FakeSockets, ScriptedModel, tool_call

MAKE, SEND, STATUS = "s__make", "s__send", "s__status"


class Core:
    def __init__(self, chat, sql, clock, model, hub, **changes):
        self.pool, self.alarms, self.hub, self.clock = FakeSockets(), FakeAlarms(), hub, clock
        settings = Settings(mcp_url="x", llm_base_url="m", llm_api_key="k", **changes)
        self.core = ChatCore(chat.id, sql, settings, model, hub, self.pool, self.alarms, clock)
        self.log = self.core.log

    async def settle(self):
        while self.core.running:
            await asyncio.sleep(0)
            await self.core._driver

    async def events(self, kind=None):
        return [e for e in await self.log.read() if kind is None or e.type == kind]


def plain(text="ok"):
    return {"content": [{"type": "text", "text": text}]}


@pytest.fixture
def rig(chat, sql, clock):
    def make(*script, **changes):
        hub = FakeHub({MAKE: plain("made"), SEND: plain("sent"), STATUS: plain("pending")}, card_uri=None)
        hub.read_only_tools = {STATUS}
        return Core(chat, sql, clock, ScriptedModel(*script), hub, **changes)

    return make


async def started_turn(c, call):
    """What a restart leaves after a call left for its connector: the reply asking for it, its
    `tool.started`, and no result."""
    await c.log.append(kinds.USER, {"text": "go"}, task="t1")
    await c.log.append(kinds.TURN_STARTED, {"task": "t1", "trigger": 1}, task="t1")
    reply = {"message": "m1", "text": "", "finish_reason": "tool_calls", "upto": 2, "tool_calls": [call]}
    await c.log.append(kinds.ASSISTANT, reply, task="t1")
    server, _, tool = call["name"].partition("__")
    await c.log.append(kinds.TOOL_STARTED, {"call_id": call["id"], "server": server, "tool": tool}, task="t1")


# --- deadlines -------------------------------------------------------------------------------------------


async def test_a_slow_tool_that_changes_something_has_an_unknown_outcome_and_the_turn_goes_on(rig):
    c = rig(("", [tool_call(SEND, {})]), "I will check first.", tool_deadline_seconds=0.02)
    c.hub.delays[SEND] = 1
    await c.core.submit(kinds.USER, "send it")
    await c.settle()
    (result,) = await c.events(kinds.TOOL)
    assert result.payload["is_error"]
    assert "Whether it went through is unknown" in result.payload["result_text"]
    assert STATUS in result.payload["result_text"], "it names the tool to check with"
    assert (await c.events(kinds.TURN_FINISHED))[0].payload["reason"] == kinds.COMPLETED


async def test_a_slow_tool_that_only_reads_is_just_too_slow(rig):
    c = rig(("", [tool_call(STATUS, {})]), "It did not answer.", tool_deadline_seconds=0.02)
    c.hub.delays[STATUS] = 1
    await c.core.submit(kinds.USER, "how is it")
    await c.settle()
    (result,) = await c.events(kinds.TOOL)
    assert result.payload["is_error"] and result.payload["result_text"] == "status did not answer in time."


# --- tool.started ----------------------------------------------------------------------------------------


async def test_every_connector_call_is_marked_started_before_it_leaves_and_no_client_shows_it(rig, chat):
    from chat.history import items

    c = rig(("", [tool_call(SEND, {})]), "Sent.")
    await c.core.submit(kinds.USER, "send it")
    await c.settle()
    types = [e.type for e in await c.events()]
    assert types.index(kinds.TOOL_STARTED) == types.index(kinds.TOOL) - 1
    shown = items(await c.events())
    assert kinds.TOOL_STARTED not in {item.kind for item in shown}


async def test_an_unkeyed_call_cut_off_after_it_left_is_not_sent_again_and_the_model_is_told(rig):
    c = rig("I will check how it stands.")
    await started_turn(c, tool_call(SEND, {}))
    await c.core.on_alarm()
    await c.settle()
    assert c.hub.calls == [], "it is not sent a second time"
    (result,) = await c.events(kinds.TOOL)
    assert "234 was restarted while send was running" in result.payload["result_text"]
    assert f"call {STATUS}" in result.payload["result_text"]


@pytest.mark.parametrize("safe", ["keyed", "read-only"])
async def test_a_call_that_is_safe_to_repeat_runs_again_after_a_restart(rig, safe):
    c = rig("Done.")
    name = MAKE if safe == "keyed" else STATUS
    if safe == "keyed":
        c.hub.keyed_tools = {MAKE}
    await started_turn(c, tool_call(name, {}))
    await c.core.on_alarm()
    await c.settle()
    assert [call for call, _ in c.hub.calls] == [name]
    assert len(await c.events(kinds.TOOL_STARTED)) == 1, "it is not marked started twice"


# --- resumes bounded by progress -------------------------------------------------------------------------


async def interrupt(c, seconds=60):
    """The object is lost mid-turn and its watchdog fires `seconds` later."""
    c.clock.advance(seconds)
    c.core._driver = None
    await c.core.on_alarm()
    await c.settle()


async def test_a_turn_that_moves_between_interruptions_is_never_given_up(rig):
    c = rig("All done.")
    await c.log.append(kinds.USER, {"text": "go"}, task="t1")
    await c.log.append(kinds.TURN_STARTED, {"task": "t1", "trigger": 1}, task="t1")
    for i in range(6):
        await c.log.append(kinds.TURN_RESUMED, {"task": "t1"}, task="t1")
        c.clock.advance(60)
        result = {"call_id": f"c{i}", "server": "s", "tool": "status", "arguments": {},
                  "result_text": "pending", "is_error": False}  # fmt: skip
        await c.log.append(kinds.TOOL, result, task="t1")
    await interrupt(c)
    finished = await c.events(kinds.TURN_FINISHED)
    assert finished and finished[0].payload["reason"] == kinds.COMPLETED


@pytest.mark.parametrize("cut", ["while it streamed", "after a call left"])
async def test_three_resumes_without_progress_fail_the_turn_once_and_the_next_alarm_leaves_it(rig, cut):
    c = rig("never reached")
    if cut == "after a call left":
        await started_turn(c, tool_call(STATUS, {}))
    else:
        await c.log.append(kinds.USER, {"text": "go"}, task="t1")
        await c.log.append(kinds.TURN_STARTED, {"task": "t1", "trigger": 1}, task="t1")
        await c.log.append(kinds.TEXT, {"message": "m1", "text": "Let me"}, task="t1")
    for _ in range(3):
        await c.log.append(kinds.TURN_RESUMED, {"task": "t1"}, task="t1")
        c.clock.advance(31)
    await interrupt(c, 0)
    (finished,) = await c.events(kinds.TURN_FINISHED)
    assert finished.payload["reason"] == kinds.FAILED and finished.payload["cause"] == kinds.RESUMES_EXHAUSTED
    assert len(await c.events(kinds.NOTICE)) == 1
    if cut == "after a call left":
        (stopped,) = await c.events(kinds.TOOL)
        assert stopped.payload["cancelled"] and "interrupted" in stopped.payload["result_text"]
    await interrupt(c)
    assert len(await c.events(kinds.TURN_STARTED)) == 1 and c.hub.calls == [], "nothing is started again"
    assert len(await c.events(kinds.TURN_FINISHED)) == 1


async def test_resumes_close_together_count_once(rig):
    c = rig("Done.")
    await started_turn(c, tool_call(STATUS, {}))
    for _ in range(3):
        await c.log.append(kinds.TURN_RESUMED, {"task": "t1"}, task="t1")
        c.clock.advance(10)
    await interrupt(c, 0)
    assert (await c.events(kinds.TURN_FINISHED))[0].payload["reason"] == kinds.COMPLETED


async def test_a_turn_with_no_progress_for_five_minutes_is_given_up(rig):
    c = rig("never reached")
    await started_turn(c, tool_call(STATUS, {}))
    await interrupt(c, 301)
    (finished,) = await c.events(kinds.TURN_FINISHED)
    assert finished.payload["cause"] == kinds.NO_PROGRESS


# --- the watchdog stops ----------------------------------------------------------------------------------


async def test_a_watchdog_whose_recovery_raises_every_time_stops_after_three(rig, monkeypatch):
    c = rig("x")
    await started_turn(c, tool_call(STATUS, {}))

    async def broken(*args, **kwargs):
        raise RuntimeError("the database is down")

    monkeypatch.setattr(c.core, "recover", broken)
    c.alarms.at = 1
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await c.core.on_alarm()
    await c.core.on_alarm()
    assert c.alarms.at is None, "the fourth alarm finds nothing changed three times and disarms"


async def test_an_alarm_that_sees_the_log_move_starts_counting_again(rig):
    c = rig("x")
    await c.log.append(kinds.USER, {"text": "go"}, task="t1")
    for _ in range(2):
        assert await c.alarms.unchanged(await c.log.last_seq()) >= 0
    await c.log.append(kinds.NOTICE, {"level": "info", "text": "moved"}, task="t1")
    assert await c.alarms.unchanged(await c.log.last_seq()) == 0


async def test_a_chat_in_a_payer_group_makes_its_turns_and_card_calls_inside_it(rig, chat, sql):
    from turns import hub as hub_module

    c = rig(("", [tool_call(SEND, {})]), "Sent.")
    await sql.execute("UPDATE chat_chat SET payer_group = ? WHERE id = ?", "cd" * 16, chat.id)
    seen = []
    called = c.hub.call_model_tool

    async def recording(*args, **kwargs):
        seen.append(hub_module._payer_group.get())
        return await called(*args, **kwargs)

    c.hub.call_model_tool = recording
    await c.core.submit(kinds.USER, "send it")
    await c.settle()
    assert seen == ["cd" * 16]


class CountingDb:
    """The database, counting the statements that write to the event log."""

    def __init__(self, inner):
        self._inner, self.event_writes = inner, []

    async def rows(self, sql, *params):
        if sql.lstrip().startswith("INSERT INTO chat_event"):
            self.event_writes.append(sql)
        return await self._inner.rows(sql, *params)

    async def row(self, sql, *params):
        found = await self.rows(sql, *params)
        return found[0] if found else None

    async def execute(self, sql, *params):
        return await self._inner.execute(sql, *params)


async def test_a_tool_result_and_its_card_are_written_in_one_statement(chat, sql, clock):
    from .support import quote_result

    hub = FakeHub({"s__make": quote_result()})
    counting = CountingDb(sql)
    made = ChatCore(
        chat.id, counting, Settings(mcp_url="x", llm_base_url="m", llm_api_key="k"),
        ScriptedModel(("", [tool_call("s__make", {}, "c1")]), "Check the card."), hub,
        FakeSockets(), FakeAlarms(), clock,
    )  # fmt: skip
    await made.submit(kinds.USER, "pay")
    while made.running:
        await asyncio.sleep(0)
        await made._driver
    events = await made.log.read()
    tool, card = (next(e for e in events if e.type == t) for t in (kinds.TOOL, kinds.CARD))
    assert card.seq == tool.seq + 1 and card.ref == "qt-1"
    pair = [sql for sql in counting.event_writes if "UNION ALL" in sql]
    assert len(pair) == 1, "the result and the card went in one statement"


# --- the model: asked again when it is busy ----------------------------------------------------------------


class Flaky:
    """A model whose first attempts fail with `errors`, each after streaming `partial`, and then answers."""

    def __init__(self, errors, answer="Hello there.", partial=""):
        self.errors, self.answer, self.partial, self.asked = list(errors), answer, partial, 0

    async def stream(self, messages, tools):
        from turns.model import Finished, TextDelta

        self.asked += 1
        if self.errors:
            if self.partial:
                yield TextDelta(self.partial)
            raise self.errors.pop(0)
        yield TextDelta(self.answer)
        yield Finished("stop", [])


def busy():
    from turns.model import ModelError

    return ModelError("The model endpoint answered HTTP 503.", transient=True)


def refused():
    from turns.model import ModelError

    return ModelError("The model endpoint answered HTTP 400.")


def asking(chat, sql, clock, model, **changes):
    """A chat core with this model, asking again at once (`model_retry_seconds` 0 unless a test says)."""
    return Core(chat, sql, clock, model, FakeHub({}), **{"model_retry_seconds": 0, **changes})


async def test_a_busy_endpoint_that_recovers_gives_one_reply_and_a_completed_turn(chat, sql, clock):
    model = Flaky([busy(), busy()])
    c = asking(chat, sql, clock, model)
    await c.core.submit(kinds.USER, "hi")
    await c.settle()
    assert model.asked == 3
    replies = await c.events(kinds.ASSISTANT)
    assert [r.payload["text"] for r in replies] == ["Hello there."] and replies[0].payload[
        "finish_reason"
    ] == "stop"
    assert (await c.events(kinds.TURN_FINISHED))[0].payload["reason"] == kinds.COMPLETED
    assert await c.events(kinds.NOTICE) == [], "the person saw no error"


async def test_a_busy_endpoint_that_stays_busy_fails_the_turn_after_its_retries(chat, sql, clock):
    model = Flaky([busy()] * 10)
    c = asking(chat, sql, clock, model, model_retries=2)
    await c.core.submit(kinds.USER, "hi")
    await c.settle()
    assert model.asked == 3, "the first attempt and two more"
    assert (await c.events(kinds.TURN_FINISHED))[0].payload["reason"] == kinds.FAILED
    assert "HTTP 503" in (await c.events(kinds.NOTICE))[0].payload["text"]


async def test_a_refused_request_is_not_asked_again(chat, sql, clock):
    model = Flaky([refused()])
    c = asking(chat, sql, clock, model)
    await c.core.submit(kinds.USER, "hi")
    await c.settle()
    assert model.asked == 1
    assert (await c.events(kinds.TURN_FINISHED))[0].payload["reason"] == kinds.FAILED


async def test_a_reply_cut_off_half_way_is_thrown_away_and_asked_for_again_under_a_new_id(chat, sql, clock):
    model = Flaky([busy()], answer="The whole answer.", partial="Half an ")
    c = asking(chat, sql, clock, model)
    await c.core.submit(kinds.USER, "hi")
    await c.settle()
    (aborted,) = await c.events(kinds.ROUND_ABORTED)
    (reply,) = await c.events(kinds.ASSISTANT)
    assert (
        reply.payload["text"] == "The whole answer."
        and reply.payload["message"] != aborted.payload["message"]
    )
    shown = [e.payload["message"] for e in await c.events(kinds.TEXT)]
    assert shown == [aborted.payload["message"], reply.payload["message"]]
    assert (await c.events(kinds.TURN_FINISHED))[0].payload["reason"] == kinds.COMPLETED


async def test_the_wait_before_asking_again_doubles(chat, sql, clock, monkeypatch):
    waits = []

    async def sleeping(seconds):
        if seconds:
            waits.append(seconds)

    monkeypatch.setattr("turns.runner.asyncio.sleep", sleeping)
    model = Flaky([busy(), busy(), busy()])
    c = asking(chat, sql, clock, model, model_retry_seconds=2)
    await c.core.submit(kinds.USER, "hi")
    await c.settle()
    assert waits == [2, 4, 8]
