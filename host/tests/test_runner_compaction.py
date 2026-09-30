# SPDX-License-Identifier: AGPL-3.0-or-later
"""The runner compacts before a model call when the context is too large, and whatever happens to the
compaction, the turn answers."""

import pytest

from turns import kinds, messages, tokens
from turns.compaction.compactor import Compactor
from turns.model import ContextTooLong, Finished, TextDelta

from .compaction_support import Rig, RoutedModel
from .support import ScriptedModel


class Usage:
    """A turn model that reports what each request cost, as the endpoint does."""

    def __init__(self, prompt_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.sent: list[list[dict]] = []

    async def stream(self, messages, tools):
        self.sent.append(messages)
        yield TextDelta("Fine. ")
        yield Finished("stop", [], {"prompt_tokens": self.prompt_tokens, "completion_tokens": 3})


@pytest.fixture
def rig(chat, sql, clock):
    def make(model=None, **changes):
        return Rig(chat, sql, clock, model or RoutedModel(), **changes)

    return make


async def test_a_turn_over_the_threshold_is_compacted_before_the_model_is_asked(rig):
    r = rig()
    await r.chat(12)
    await r.say("what now?")
    types = [e.type for e in await r.log.read(limit=10000)]
    assert types.count(kinds.COMPACTION) == 1
    tail = types[types.index(kinds.COMPACTION) - 2 :]
    assert tail[:3] == [kinds.USER, kinds.TURN_STARTED, kinds.COMPACTION] and tail[-1] == kinds.TURN_FINISHED
    sent = r.model.sent[-1]
    assert sent[1]["content"].startswith(messages.SUMMARY_LABEL) and sent[-1]["content"] == "what now?"
    assert "talk 0" not in str(sent)


async def test_the_reply_records_how_far_it_read_including_the_compaction(rig):
    r = rig()
    await r.chat(12)
    await r.say("what now?")
    compaction = (await r.compactions())[0]
    reply = [e for e in await r.log.read(limit=10000) if e.type == kinds.ASSISTANT][-1]
    assert reply.payload["upto"] >= compaction.seq


async def test_the_context_a_turn_sends_stays_under_the_threshold(rig):
    r = rig(context_window_tokens=4000, keep_recent_tokens=500)
    sizes = []
    for n in range(40):
        await r.say(f"turn {n} {'a' * 440}")
        sizes.append(tokens.request_tokens(r.model.sent[-1], []))
    assert max(sizes) <= r.settings.compact_threshold_tokens
    assert len(await r.compactions()) >= 3


async def test_a_reply_records_the_estimate_and_what_the_provider_counted(rig):
    r = rig(Usage(prompt_tokens=777))
    await r.say("hi")
    reply = (await r.log.read())[-2]
    assert reply.type == kinds.ASSISTANT
    assert reply.payload["usage"] == {"prompt_tokens": 777, "completion_tokens": 3}
    assert reply.payload["estimate"] > 0


async def test_a_model_that_reports_no_usage_leaves_the_reply_as_it_was(rig):
    r = rig(ScriptedModel("Fine."))
    await r.say("hi")
    reply = next(e for e in await r.log.read() if e.type == kinds.ASSISTANT)
    assert "usage" not in reply.payload and "estimate" not in reply.payload


async def test_what_the_provider_counted_makes_the_next_turn_compact_sooner(rig):
    r = rig(Usage(prompt_tokens=2400), context_window_tokens=2000)
    await r.say("one")
    estimate = (await r.log.read())[-2].payload["estimate"]
    assert estimate < 1000 < estimate * 3
    await r.chat(8, each=40)
    await r.say("two")
    assert await r.compactions()


class Broken(Compactor):
    async def before_round(self, events, system, tools):
        raise RuntimeError("the compactor is broken")


async def test_a_compactor_that_raises_never_fails_the_turn(rig, caplog):
    r = rig()
    r.runner._compactor = Broken(r.log, r.model, r.settings, lambda: 0, r.compactor._permit)
    await r.chat(12)
    await r.say("still there?")
    finished = [e for e in await r.log.read(limit=10000) if e.type == kinds.TURN_FINISHED][-1]
    assert finished.payload["reason"] == "completed"
    assert "the round goes on without it" in caplog.text
    assert [e.payload["text"] for e in await r.log.read(limit=10000) if e.type == kinds.ASSISTANT][
        -1
    ] == "Fine. "


async def test_a_summary_counts_as_a_model_call_against_the_daily_caps(rig, chat, sql, clock):
    from turns.budget import day_of

    r = rig(visitor_model_calls_per_day=2)
    await r.chat(12)
    await r.say("one")
    used = await sql.row("SELECT used FROM chat_budget WHERE scope = ? AND day = ?", "v:a", day_of(clock()))
    assert used["used"] == 2 and len(r.model.summaries) == 1
    await r.say("two")
    notices = [e.payload["text"] for e in await r.log.read(limit=10000) if e.type == kinds.NOTICE]
    assert any("today's share" in text for text in notices)


async def test_a_turn_with_tool_calls_keeps_the_calls_and_results_paired_across_a_compaction(rig):
    r = rig(
        RoutedModel(
            ScriptedModel(("", [{"id": "c1", "name": "s__make", "arguments": "{}"}]), "Made it.", "ok", "ok"),
        )
    )
    await r.chat(12)
    await r.say("make one")
    sent = r.model.sent[-1]
    roles = [m["role"] for m in sent]
    assert roles[-2:] == ["assistant", "tool"] or roles[-1] == "user"
    tool_ids = {m["tool_call_id"] for m in sent if m["role"] == "tool"}
    call_ids = {c["id"] for m in sent for c in m.get("tool_calls", [])}
    assert tool_ids == call_ids


async def test_a2a_and_the_page_read_the_same_log_with_a_compaction_in_it(rig):
    from a2a import wire

    r = rig()
    await r.chat(12)
    await r.say("what now?")
    events = await r.log.read(limit=10000)
    task = events[-1].task
    mine = [e for e in events if e.task == task]
    assert all(e.type != kinds.COMPACTION for e in mine)
    snapshot = wire.snapshot(task, "c", mine, "http://h")
    assert snapshot["status"]["state"] == "TASK_STATE_COMPLETED"


class Refuses:
    """A model whose endpoint refuses the first request as too long, and answers after that."""

    def __init__(self, refusals: int = 1) -> None:
        self.refusals, self.sent = refusals, []

    async def stream(self, messages, tools):
        self.sent.append(messages)
        if len(self.sent) <= self.refusals:
            raise ContextTooLong("The model endpoint answered HTTP 400.")
        yield TextDelta("Fine. ")
        yield Finished("stop", [])


async def test_a_context_the_endpoint_refuses_is_trimmed_and_the_round_is_asked_again_once(rig):
    model = Refuses()
    r = rig(RoutedModel(model), context_window_tokens=100000)
    await r.chat(12)
    await r.say("what now?")
    assert len(model.sent) == 2
    assert tokens.request_tokens(model.sent[1], []) < tokens.request_tokens(model.sent[0], [])
    (compaction,) = await r.compactions()
    assert compaction.payload["trigger"] == "fallback"
    finished = [e for e in await r.log.read(limit=10000) if e.type == kinds.TURN_FINISHED][-1]
    assert finished.payload["reason"] == "completed"


async def test_a_context_refused_twice_ends_the_turn_as_failed_like_any_model_error(rig):
    r = rig(RoutedModel(Refuses(refusals=2)), context_window_tokens=100000)
    await r.chat(12)
    await r.say("what now?")
    finished = [e for e in await r.log.read(limit=10000) if e.type == kinds.TURN_FINISHED][-1]
    assert finished.payload["reason"] == "failed"
