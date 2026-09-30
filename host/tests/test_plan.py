# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where the conversation is cut: table-driven over the rules a cut must keep."""

import pytest

from turns import kinds, messages
from turns.compaction import plan
from turns.compaction.plan import Cut

from .log_builder import Log

NOW = 1_790_000_000_000
TURN_TOKENS = 2 * (250 + 4)
EVENTS_PER_TURN = 4


def filler(tokens: int) -> str:
    return "a" * (4 * tokens)


def chat(turns: int, each: int = 250) -> Log:
    log = Log()
    for n in range(turns):
        log.turn(f"{n} {filler(each)}"[: 4 * each], filler(each))
    return log


def kept_tokens(log: Log, cut: Cut) -> int:
    units, _ = plan.live_units(log.events)
    return sum(plan.unit_tokens(u, 1.0) for u in units if u.first > cut.last)


@pytest.mark.parametrize(
    ("turns", "keep", "kept_turns"),
    [
        (10, 1000, 2),
        (10, TURN_TOKENS, 1),
        (10, TURN_TOKENS + 1, 2),
        (10, 0, 1),
        (10, 3 * TURN_TOKENS, 3),
        (3, 6000, None),
        (10, 10**9, None),
        (1, 0, None),
    ],
    ids=[
        "two turns",
        "exactly one",
        "just over one",
        "no minimum",
        "three turns",
        "a short chat",
        "keeps all",
        "one turn",
    ],
)
def test_the_cut_keeps_the_fewest_whole_turns_that_hold_the_recent_tokens(turns, keep, kept_turns):
    log = chat(turns)
    cut = plan.choose_cut(log.events, keep, NOW)
    if kept_turns is None:
        assert cut is None
        return
    assert cut is not None and cut.first == 1
    assert cut.last == EVENTS_PER_TURN * (turns - kept_turns)
    assert kept_tokens(log, cut) >= keep


def test_the_cut_keeps_at_least_the_recent_tokens_asked_for_however_uneven_the_turns():
    log = Log()
    for size in (50, 900, 30, 400, 20, 700, 10, 60):
        log.turn(filler(size), filler(size))
    for keep in (1, 100, 500, 1000, 1500, 2500):
        cut = plan.choose_cut(log.events, keep, NOW)
        assert cut is None or kept_tokens(log, cut) >= keep


def test_a_reply_that_a_message_overtook_is_cut_whole_or_not_at_all():
    """The person wrote again while the model was calling a tool: their message sits between the call and its
    result in the log, and after the reply in the conversation."""
    log = Log()
    log.user(filler(400))
    log.reply(filler(400), upto=1)
    log.user(filler(400))
    log.reply("", [log.call("s__make", {})], upto=3)
    arrived = log.user(filler(400))
    log.result({"id": "call_1", "name": "s__make", "arguments": "{}"}, filler(400))
    log.reply(filler(400), upto=arrived.seq)
    units, _ = plan.live_units(log.events)
    seqs = plan._seq_of_cut(units)
    exchange = next(i for i, u in enumerate(units) if u.last == 6)
    assert exchange + 1 not in seqs
    for keep in range(1, 1800, 100):
        cut = plan.choose_cut(log.events, keep, NOW)
        assert cut is None or cut.last not in (4, 5)


def test_a_call_still_waiting_for_its_result_pins_its_reply_and_all_after_it():
    log = chat(6)
    log.user("pay")
    waiting = log.reply("", [log.call("s__make", {})])
    log.user(filler(400))
    cut = plan.choose_cut(log.events, 0, NOW)
    assert cut is not None and cut.last < waiting.seq


def test_the_flow_of_the_latest_open_quote_is_kept_from_the_reply_that_made_it():
    log = chat(4)
    log.user("airtime")
    made = log.last + 1
    log.quote("qt-a", 50000, "airtime")
    log.reply("Please approve.")
    for n in range(8):
        log.turn(f"talk {n} {filler(250)}", filler(250))
    cut = plan.choose_cut(log.events, 1000, NOW)
    assert cut is not None and cut.last < made
    log.state("qt-a", "succeeded", 50000, "airtime")
    settled = plan.choose_cut(log.events, 1000, NOW)
    assert settled is not None and settled.last > made


def test_a_quote_whose_time_ran_out_does_not_hold_the_conversation_back():
    log = chat(4)
    log.quote("qt-a", 50000, "airtime", expires_ms=NOW - 1000)
    for n in range(8):
        log.turn(f"talk {n} {filler(250)}", filler(250))
    assert plan.choose_cut(log.events, 1000, NOW).last > 8


def test_an_older_open_quote_is_summarised_and_only_the_latest_is_kept():
    log = chat(2)
    log.quote("qt-old", 10000, "airtime")
    for n in range(4):
        log.turn(f"talk {n} {filler(250)}", filler(250))
    newer = log.last + 1
    log.quote("qt-new", 20000, "airtime")
    log.turn(filler(250), filler(250))
    cut = plan.choose_cut(log.events, 400, NOW)
    assert cut is not None and cut.last < newer and cut.last > 9


def test_when_no_turn_starts_late_enough_the_cut_falls_between_replies_of_one_turn():
    log = Log()
    log.user(filler(100))
    for n in range(6):
        log.exchange("s__look", {"n": n}, filler(400), text=filler(20))
    log.reply(filler(100))
    cut = plan.choose_cut(log.events, 1000, NOW)
    assert cut is not None and cut.last > 1
    units, _ = plan.live_units(log.events)
    starts = {plan._seq_of_cut(units)[i] for i in range(len(units)) if i in plan._seq_of_cut(units)}
    assert cut.last + 1 in starts
    assert not any(e.seq == cut.last + 1 and e.type == kinds.TOOL for e in log.events)


def test_a_cut_needs_something_worth_summarising():
    log = chat(3, each=10)
    assert plan.choose_cut(log.events, 0, NOW) is None


def test_the_next_compaction_begins_where_the_last_cut_fell_and_reads_only_what_was_kept():
    log = chat(10)
    first = plan.choose_cut(log.events, 1000, NOW)
    log.compaction(first.last, "Earlier.")
    for n in range(10):
        log.turn(f"more {n} {filler(250)}", filler(250))
    second = plan.choose_cut(log.events, 1000, NOW)
    assert second.first == first.last + 1 and second.last > first.last
    units, origin = plan.live_units(log.events)
    assert origin == first.last + 1 and all(u.first > first.last for u in units)


def test_the_units_a_cut_keeps_are_those_the_model_is_sent_after_the_summary():
    log = chat(10)
    cut = plan.choose_cut(log.events, 1000, NOW)
    log.compaction(cut.last, "Earlier.")
    sent = messages.render(log.events, "sys")
    assert len(sent) == 1 + 1 + 2 * 2


def test_trimming_stubs_old_bulky_results_and_stops_when_that_is_enough():
    log = Log()
    for n in range(6):
        log.user(f"list {n}")
        log.exchange("s__plans", {}, "Plans:\n" + "\n".join(f"p{i}: Plan {i}" for i in range(60)))
        log.reply("there", upto=log.last)
    before = sum(plan.unit_tokens(u, 1.0) for u in plan.live_units(log.events)[0])
    result = plan.trim(log.events, 0, before - 100, 600, NOW, 1.0)
    assert result.cut is None and result.pruned_before > 1
    units, _ = plan.live_units(log.events, result.pruned_before)
    assert sum(plan.unit_tokens(u, 1.0) for u in units) <= before - 100


def test_trimming_drops_the_fewest_oldest_messages_that_fit_and_respects_an_open_quote():
    log = chat(10)
    log.quote("qt-a", 50000, "airtime")
    made = log.events[-3].seq
    for n in range(5):
        log.turn(f"talk {n} {filler(250)}", filler(250))
    total = sum(plan.unit_tokens(u, 1.0) for u in plan.live_units(log.events)[0])
    modest = plan.trim(log.events, 0, total - 3 * TURN_TOKENS, 500, NOW, 1.0)
    assert modest.cut is not None and modest.cut.last < made
    tight = plan.trim(log.events, 0, 2 * TURN_TOKENS, 500, NOW, 1.0)
    assert tight.cut is not None and tight.cut.last > made
    assert modest.cut.last < tight.cut.last


def test_trimming_with_nothing_that_can_be_cut_only_stubs():
    log = Log()
    log.user(filler(100))
    result = plan.trim(log.events, 0, 10, 50, NOW, 1.0)
    assert result.cut is None
