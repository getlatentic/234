# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compaction at the compactor: when it runs, what it writes, what it keeps, and what it does when the
summary cannot be had. The runner's side of it is in test_runner_compaction.py."""

import asyncio
import json
import logging

import pytest

from turns import kinds, messages
from turns.compaction import facts as facts_module
from turns.compaction.compactor import identity
from turns.model import ModelError

from .compaction_support import Rig, RoutedModel, filler, seed_quotes
from .log_builder import quote_view

SYSTEM = "sys"
TOOLS: list = []


@pytest.fixture
def rig(chat, sql, clock):
    def make(model=None, **changes):
        return Rig(chat, sql, clock, model or RoutedModel(), **changes)

    return make


async def test_nothing_happens_while_the_context_is_under_the_threshold(rig):
    r = rig()
    await r.chat(3)
    assert not await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    assert not r.model.summaries and not await r.compactions()


async def test_over_the_threshold_one_compaction_is_written_with_what_it_covers_and_what_it_cost(rig):
    r = rig()
    await r.chat(14)
    events = await r.events()
    assert await r.compactor.before_round(events, SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    payload = compaction.payload
    assert payload["trigger"] == "auto" and payload["model"] == r.settings.llm_model
    assert payload["covers"]["first"] == 1 and payload["covers"]["last"] > 1
    assert payload["tokens"]["after"] < payload["tokens"]["before"]
    assert payload["tokens"]["after"] <= r.settings.compact_threshold_tokens
    assert payload["verified"] == "model" and payload["calls"] == 1 and payload["pruned_before"] == 0
    assert compaction.ref == identity(1, payload["covers"]["last"], 0) and compaction.task is None
    assert payload["summary"].startswith("## Asked and decided")
    sent = messages.render(await r.events(), SYSTEM)
    assert sent[1]["content"].endswith(payload["summary"])
    assert sum(len(m["content"]) for m in sent) < sum(
        len(m["content"]) for m in messages.render(events, SYSTEM)
    )


async def test_the_log_is_never_rewritten(rig):
    r = rig()
    await r.chat(14)
    before = [e.wire() for e in await r.log.read(limit=10000)]
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    after = [e.wire() for e in await r.log.read(limit=10000)]
    assert after[: len(before)] == before and len(after) == len(before) + 1
    assert [e["seq"] for e in after] == list(range(1, len(after) + 1))


async def test_the_model_reads_the_tail_word_for_word_after_the_summary(rig):
    r = rig()
    await r.chat(14)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    sent = messages.render(await r.events(), SYSTEM)
    assert sent[-2]["content"].startswith("talk 13") and sent[-1]["content"] == "Fine. "
    assert "talk 0" not in " ".join(m["content"] for m in sent[2:])


async def test_a_second_compaction_updates_the_first_summary_and_covers_only_what_was_kept(rig):
    r = rig()
    await r.chat(14)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (first,) = await r.compactions()
    await r.chat(14, prefix="later")
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    first, second = await r.compactions()
    assert second.payload["covers"]["first"] == first.payload["covers"]["last"] + 1
    assert "<previous_record>" in r.model.summaries[1][-1]["content"]
    assert first.payload["summary"].splitlines()[1] in r.model.summaries[1][-1]["content"]
    assert messages.latest_compaction(await r.events()).seq == second.seq


async def test_what_the_person_said_survives_two_compactions(rig):
    r = rig()
    await r.say("Send 5k to Ada Okafor, GTBank 0123456789, from 07031234567")
    await r.chat(14)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    await r.chat(14, prefix="later")
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    first, second = await r.compactions()
    events = await r.events()
    for compaction in (first, second):
        before_cut = [e for e in events if e.seq <= compaction.payload["covers"]["last"]]
        needed = facts_module.facts_of_events(before_cut)
        assert needed.amounts and needed.phones and needed.accounts
        assert not facts_module.missing_from(compaction.payload["summary"], needed, facts_module.Facts())


async def test_a_summary_that_forgot_a_fact_is_asked_for_again_with_the_missing_facts_listed(rig):
    r = rig(RoutedModel(mode="forgets_first"))
    await r.say("Send 5k to Ada Okafor, GTBank 0123456789")
    await r.chat(14)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    assert compaction.payload["verified"] == "retried" and compaction.payload["calls"] == 2
    asked_again = r.model.summaries[1][-1]["content"]
    assert "left these out" in asked_again and "₦5,000" in asked_again and "0123456789" in asked_again
    assert "₦5,000" in compaction.payload["summary"] and "0123456789" in compaction.payload["summary"]


async def test_a_summary_that_still_forgets_is_completed_with_the_facts_written_by_rule(rig):
    r = rig(RoutedModel(mode="forgetful"))
    await r.say("Send 5k to Ada Okafor, GTBank 0123456789, from 07031234567")
    await seed_quotes(r, [("qt-open", 50000, "awaiting_approval"), ("qt-paid", 500000, "succeeded")])
    await r.chat(14)
    await seed_quotes(r, [("qt-late", 77700, "awaiting_approval")])
    await r.chat(2)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    summary = compaction.payload["summary"]
    assert compaction.payload["verified"] == "block" and compaction.payload["calls"] == 2
    assert facts_module.FACTS_HEADING in summary
    for fact in (
        "₦5,000",
        "₦500",
        "0123456789",
        "07031234567",
        "qt-open: awaiting_approval (open)",
        "qt-paid: succeeded",
    ):
        assert fact in summary


async def test_a_retry_that_fails_outright_still_ends_with_the_block(rig):
    calls = []

    def second_is_junk(request):
        calls.append(request)
        return (
            "ok"
            if len(calls) > 1
            else "## Asked and decided\n- a\n## Done\n- b\n## Pending\n- c\n" + "x" * 80
        )

    r = rig(RoutedModel(mode=second_is_junk))
    await r.say("Send 5k to Ada, GTBank 0123456789")
    await r.chat(14)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    assert (
        compaction.payload["verified"] == "block"
        and facts_module.FACTS_HEADING in compaction.payload["summary"]
    )


@pytest.mark.parametrize(
    ("model", "reason"),
    [
        (RoutedModel(mode=ModelError("The model endpoint answered HTTP 500.")), "HTTP 500"),
        (RoutedModel(mode="junk"), "not in the sections"),
        (RoutedModel(mode=RuntimeError("boom")), "RuntimeError"),
        (RoutedModel(mode=lambda request: 1 / 0), "ZeroDivisionError"),
    ],
    ids=["an HTTP error", "not a summary", "a crash", "a bug in the summariser"],
)
async def test_a_summary_that_cannot_be_had_falls_back_to_trimming_and_the_turn_goes_on(
    rig, caplog, model, reason
):
    r = rig(model)
    await r.chat(14)
    with caplog.at_level(logging.WARNING):
        assert await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    payload = compaction.payload
    assert payload["trigger"] == "fallback" and reason in payload["reason"] and payload["model"] == ""
    assert payload["tokens"]["after"] <= r.settings.compact_threshold_tokens
    assert any("fell back to trimming" in m and reason in m for m in caplog.messages)
    assert not any(e.type == kinds.NOTICE for e in await r.events())
    await r.say("one more")
    assert (await r.events())[-1].type == kinds.TURN_FINISHED


async def test_a_summary_that_takes_too_long_falls_back(rig):
    r = rig(RoutedModel(slow=5), compaction_timeout_seconds=0.05)
    await r.chat(14)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    assert compaction.payload["trigger"] == "fallback" and "timed out" in compaction.payload["reason"]


async def test_a_summary_the_model_budget_does_not_allow_falls_back_and_spends_nothing(rig):
    r = rig()
    await r.chat(14)
    r.deny_summaries()
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    assert compaction.payload["trigger"] == "fallback" and "budget" in compaction.payload["reason"]
    assert not r.model.summaries


async def test_the_fallback_keeps_the_facts_of_what_it_dropped_and_the_log_keeps_the_rest(rig):
    r = rig(RoutedModel(mode=ModelError("down")))
    await r.say("Send 5k to Ada, GTBank 0123456789, from 07031234567")
    await r.chat(14)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    assert compaction.payload["covers"]["last"] > 1
    for fact in ("₦5,000", "0123456789", "07031234567"):
        assert fact in compaction.payload["summary"]
    assert any("Send 5k" in e.payload.get("text", "") for e in await r.log.read(limit=10000))


async def test_the_fallback_stubs_old_bulky_results_before_it_drops_anything(rig):
    r = rig(RoutedModel(mode=ModelError("down")))
    plans = "Plans:\n" + "\n".join(f"p{i}: Plan number {i}" for i in range(60))
    for n in range(4):
        await r.call(f"plans {n}", f"c{n}", plans)
    await r.chat(3, each=60)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    assert compaction.payload["trigger"] == "fallback" and compaction.payload["pruned_before"] > 0
    sent = [m["content"] for m in messages.render(await r.events(), SYSTEM) if m["role"] == "tool"]
    assert "[result omitted: 60 items]" in sent


async def test_two_rounds_that_find_the_context_too_large_at_once_make_one_compaction(rig):
    r = rig(RoutedModel(slow=0.02))
    await r.chat(14)
    events = await r.events()
    await asyncio.gather(*(r.compactor.before_round(events, SYSTEM, TOOLS) for _ in range(4)))
    assert len(await r.compactions()) == 1 and len(r.model.summaries) == 1


async def test_two_manual_requests_made_together_make_one_compaction_and_both_answer_with_it(rig):
    r = rig(RoutedModel(slow=0.02))
    await r.chat(14)
    first, second = await asyncio.gather(
        r.compactor.manual(SYSTEM, TOOLS, 100), r.compactor.manual(SYSTEM, TOOLS, 100)
    )
    assert first is not None and second is not None and first.seq == second.seq
    assert len(await r.compactions()) == 1


async def test_a_manual_request_after_the_first_has_finished_compacts_what_is_new(rig):
    r = rig()
    await r.chat(14)
    first = await r.compactor.manual(SYSTEM, TOOLS, 100)
    await r.chat(8, prefix="later")
    second = await r.compactor.manual(SYSTEM, TOOLS, 100)
    assert first is not None and second is not None and second.seq > first.seq


async def test_a_manual_request_with_nothing_worth_summarising_writes_nothing(rig):
    r = rig()
    await r.say("hi")
    assert await r.compactor.manual(SYSTEM, TOOLS) is None
    assert not await r.compactions()


async def test_a_manual_compaction_happens_under_the_threshold(rig):
    r = rig(context_window_tokens=32000, keep_recent_tokens=6000)
    await r.chat(14)
    assert await r.compactor.manual(SYSTEM, TOOLS, 100) is not None
    (compaction,) = await r.compactions()
    assert compaction.payload["trigger"] == "manual"


async def test_an_identical_compaction_is_written_once_however_often_it_is_attempted(rig):
    r = rig()
    await r.chat(3)
    payload = {"covers": {"first": 1, "last": 2}, "summary": "s", "trigger": "auto"}
    ref = identity(1, 2, 0)
    first = await r.log.append_next_of_type(kinds.COMPACTION, payload, ref=ref, newest=0)
    again = await r.log.append_next_of_type(kinds.COMPACTION, payload, ref=ref, newest=0)
    after_it = await r.log.append_next_of_type(kinds.COMPACTION, payload, ref=ref, newest=first.seq)
    other = await r.log.append_next_of_type(kinds.COMPACTION, payload, ref=identity(1, 3, 0), newest=0)
    assert first is not None and again is None and after_it is None and other is None
    assert len(await r.compactions()) == 1


async def test_a_restarted_runner_finds_the_compaction_in_the_log_and_writes_no_second(rig, chat, sql, clock):
    r = rig()
    await r.chat(14)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    again = Rig(chat, sql, clock, RoutedModel())
    assert not await again.compactor.before_round(await again.events(), SYSTEM, TOOLS)
    assert len(await r.compactions()) == 1 and not again.model.summaries


TOKEN = "ab" * 32
LINK = "https://checkout.paystack.com/xyz123"


async def test_no_token_and_no_link_reaches_the_summariser_or_the_summary(rig):
    r = rig()
    await r.say(f"my link is {LINK} and my key is sk_live_abcdef123456789")
    await r.log.append(
        kinds.CARD,
        {"server": "s", "result": {**quote_view("qt-a", "awaiting_approval", 50000, "airtime"),
                                   "_meta": {"approvalToken": TOKEN}}},
        ref="qt-a",
    )  # fmt: skip
    view = quote_view("qt-a", "awaiting_checkout", 50000, "airtime")
    view["structuredContent"]["quote"]["checkoutUrl"] = LINK
    await r.log.append(kinds.CARD_STATE, {"result": view}, ref="qt-a")
    await r.chat(14)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    everything = json.dumps(r.model.summaries) + compaction.payload["summary"]
    for secret in (TOKEN, LINK, "checkout.paystack.com", "sk_live_abcdef123456789"):
        assert secret not in everything


async def test_a_summariser_that_writes_a_secret_anyway_is_scrubbed(rig):
    def leaky(request):
        return (
            "## Asked and decided\n- paid\n## Facts the person stated\n- none\n"
            f"## Done\n- see {LINK} and {TOKEN}\n## Pending\n- none\n## Tone and language\n- English"
            + "."
            * 40
        )

    r = rig(RoutedModel(mode=leaky))
    await r.chat(14)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    assert (
        TOKEN not in compaction.payload["summary"]
        and "checkout.paystack.com" not in compaction.payload["summary"]
    )


async def test_the_latest_open_quote_stays_in_front_of_the_model_word_for_word(rig):
    r = rig()
    await r.chat(3)
    made = await r.call("airtime please", "cq", "Quote qt-open: ₦500.")
    await seed_quotes(r, [("qt-open", 50000, "awaiting_approval")])
    await r.chat(12, prefix="after")
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    assert compaction.payload["covers"]["last"] < made.seq
    sent = json.dumps(messages.render(await r.events(), SYSTEM), ensure_ascii=False)
    assert "Quote qt-open: ₦500." in sent and "airtime please" in sent


async def test_an_unanswered_call_is_never_split_from_the_result_that_is_still_to_come(rig):
    r = rig()
    await r.chat(12)
    waiting = await r.call("pay", "cw", None)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    assert compaction.payload["covers"]["last"] < waiting.seq
    await r.log.append(
        kinds.TOOL,
        {
            "call_id": "cw",
            "server": "s",
            "tool": "make",
            "arguments": {},
            "result_text": "made",
            "is_error": False,
        },
    )
    sent = messages.render(await r.events(), SYSTEM)
    assert [m["role"] for m in sent[-3:]] == ["user", "assistant", "tool"] and sent[-1]["content"] == "made"


async def test_a_context_no_cut_can_shrink_is_left_alone_until_it_is_over_the_hard_limit(rig):
    r = rig(keep_recent_tokens=10**6)
    await r.chat(9)
    assert not await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    hard = rig(keep_recent_tokens=10**6, context_window_tokens=1000)
    await hard.chat(14)
    assert await hard.compactor.before_round(await hard.events(), SYSTEM, TOOLS)
    (compaction,) = await hard.compactions()
    assert compaction.payload["trigger"] == "fallback"


async def test_the_provider_count_corrects_the_estimate_that_decides_when_to_compact(rig):
    r = rig()
    await r.chat(4, each=80)
    events = await r.events()
    assert not await r.compactor.before_round(events, SYSTEM, TOOLS)
    last = events[-1]
    await r.log.append(
        kinds.ASSISTANT,
        {"message": "mu", "text": "x", "finish_reason": "stop", "upto": last.seq, "estimate": 100,
         "usage": {"prompt_tokens": 300}},
    )  # fmt: skip
    assert await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)


def test_the_filler_is_the_size_the_tests_think_it_is():
    assert len(filler(10)) == 40


async def test_a_summary_far_too_long_is_not_accepted_and_the_fallback_trims(rig):
    def rambling(request):
        return "\n".join(
            ["## Asked and decided", "- a", "## Done", "- b", "## Pending"] + ["- " + "word " * 40] * 400
        )

    r = rig(RoutedModel(mode=rambling))
    await r.chat(14)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    assert compaction.payload["trigger"] == "fallback" and "too long" in compaction.payload["reason"]


async def test_a_chat_that_is_being_deleted_gets_no_compaction(rig):
    r = rig(RoutedModel(slow=0.02))
    await r.chat(14)
    running = asyncio.ensure_future(r.compactor.manual(SYSTEM, TOOLS, 100))
    await asyncio.sleep(0)
    r.compactor.close()
    assert await running is None
    assert not await r.compactions()


async def test_an_endpoint_that_says_the_context_is_too_long_gets_a_trimmed_one_without_a_summary(rig):
    r = rig()
    await r.chat(14)
    assert await r.compactor.squeeze(SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    assert compaction.payload["trigger"] == "fallback" and "too long" in compaction.payload["reason"]
    assert not r.model.summaries
    assert compaction.payload["tokens"]["after"] <= compaction.payload["tokens"]["before"] * 0.5 + 50


async def test_a_context_that_a_compaction_would_shrink_by_little_is_not_compacted_again_and_again(rig):
    """With a window this small next to the system prompt, each turn is over the threshold: only a cut that
    covers a fair share of what is kept is worth a model call."""
    r = rig(context_window_tokens=1300, keep_recent_tokens=400)
    await r.chat(14)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    calls = len(r.model.summaries)
    for n in range(6):
        await r.chat(1, prefix=f"more{n}")
        await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    assert len(r.model.summaries) - calls <= 3


async def test_a_summary_is_never_asked_of_a_claude_model(chat, sql, clock):
    import httpx

    from turns.model import OpenAICompatible

    from .compaction_support import small

    asked = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: asked.append(request)))
    name = "us.anthropic.claude-sonnet-4"
    r = Rig(chat, sql, clock, OpenAICompatible(small(llm_model=name), client), llm_model=name)
    await r.chat(14)
    await r.compactor.before_round(await r.events(), SYSTEM, TOOLS)
    (compaction,) = await r.compactions()
    assert compaction.payload["trigger"] == "fallback" and "Claude" in compaction.payload["reason"]
    assert asked == []
