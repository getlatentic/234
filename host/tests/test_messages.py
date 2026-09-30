# SPDX-License-Identifier: AGPL-3.0-or-later
"""The messages the model reads: only text, replies where they belong, and, after a compaction, the summary
and what the log holds from the cut on."""

from turns import kinds, messages
from turns.eventlog import Event

from .log_builder import Log


def ev(seq, type, payload=None, task=None, ref=None):
    return Event(seq, type, task, ref, payload or {}, 0)


def reply(seq, text="", calls=(), upto=0, message="m"):
    payload = {"message": message, "text": text, "finish_reason": "stop", "upto": upto}
    if calls:
        payload["tool_calls"] = list(calls)
    return ev(seq, kinds.ASSISTANT, payload)


CALL = {"id": "c1", "name": "s__make", "arguments": "{}"}
RESULT = ev(3, kinds.TOOL, {"call_id": "c1", "result_text": "made it", "tool": "make", "is_error": False})


def test_the_model_reads_text_only_and_a_tool_result_follows_its_call():
    events = [
        ev(1, kinds.USER, {"text": "pay"}),
        reply(2, "", [CALL], upto=1),
        RESULT,
        ev(4, kinds.CARD, {"result": {"_meta": {"approvalToken": "tok-secret"}}}, ref="q"),
        ev(5, kinds.CARD_CONTEXT, {"text": "The card now shows: paid."}),
        reply(6, "done", upto=5),
    ]
    sent = messages.render(events, "sys")
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "tool", "user", "assistant"]
    assert sent[3] == {"role": "tool", "tool_call_id": "c1", "content": "made it"}
    assert sent[4]["content"] == "[card update] The card now shows: paid."
    assert "tok-secret" not in str(sent)


def test_a_message_that_arrived_between_a_call_and_its_result_does_not_split_them():
    events = [
        ev(1, kinds.USER, {"text": "pay"}),
        reply(2, "", [CALL], upto=1),
        ev(3, kinds.USER, {"text": "and quickly"}),
        ev(4, kinds.TOOL, {"call_id": "c1", "result_text": "made it", "tool": "make", "is_error": False}),
    ]
    roles = [m["role"] for m in messages.render(events, "sys")]
    assert roles == ["system", "user", "assistant", "tool", "user"]


def test_a_reply_follows_what_it_had_read_not_what_arrived_while_it_streamed():
    events = [
        ev(1, kinds.USER, {"text": "one"}),
        ev(2, kinds.USER, {"text": "two"}),
        reply(3, "answer to one", upto=1),
    ]
    contents = [m["content"] for m in messages.render(events, "sys")[1:]]
    assert contents == ["one", "answer to one", "two"]


def test_a_reply_with_nothing_in_it_is_not_sent_back_to_the_model():
    events = [ev(1, kinds.USER, {"text": "hi"}), reply(2, "", upto=1)]
    assert [m["role"] for m in messages.render(events, "sys")] == ["system", "user"]


def test_card_messages_are_marked_as_the_cards_not_the_person():
    events = [ev(1, kinds.CARD_MESSAGE, {"text": "hello"})]
    assert messages.render(events, "s")[1]["content"] == "[card message] hello"


def test_a_call_with_no_result_yet_is_shown_as_not_run():
    events = [ev(1, kinds.USER, {"text": "pay"}), reply(2, "", [CALL], upto=1)]
    assert messages.render(events, "s")[-1] == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": messages.NO_RESULT,
    }


def test_after_a_compaction_the_model_reads_the_summary_then_what_follows_the_cut():
    log = Log()
    log.turn("first", "one")
    log.turn("second", "two")
    cut_after = log.last
    log.turn("third", "three")
    log.compaction(cut_after, "They asked for first and second.")
    sent = messages.render(log.events, "sys")
    assert [m["role"] for m in sent] == ["system", "user", "user", "assistant"]
    assert sent[1]["content"].startswith(messages.SUMMARY_LABEL)
    assert sent[1]["content"].endswith("They asked for first and second.")
    assert [m["content"] for m in sent[2:]] == ["third", "three"]


def test_a_later_compaction_replaces_the_earlier_summary():
    log = Log()
    log.turn("first", "one")
    log.compaction(log.last, "Summary A.")
    log.turn("second", "two")
    log.compaction(log.last, "Summary B.")
    log.turn("third", "three")
    sent = messages.render(log.events, "sys")
    assert "Summary B." in sent[1]["content"] and "Summary A." not in str(sent)
    assert [m["content"] for m in sent[2:]] == ["third", "three"]


def test_a_compaction_with_no_summary_adds_no_message():
    log = Log()
    log.turn("first", "one")
    log.compaction(0, "")
    assert [m["role"] for m in messages.render(log.events, "sys")] == ["system", "user", "assistant"]


def test_old_bulky_results_are_stubbed_after_a_fallback_and_recent_ones_stay():
    plans = "MTN data plans:\n" + "\n".join(f"code{i}: Plan {i}, ₦{i}00" for i in range(30))
    log = Log()
    log.user("plans")
    log.exchange("a__list_plans", {}, plans)
    log.user("again")
    log.exchange("a__list_plans", {}, plans)
    boundary = log.events[-2].seq
    log.compaction(0, "", pruned_before=boundary)
    tools = [m["content"] for m in messages.render(log.events, "s") if m["role"] == "tool"]
    assert tools == ["[result omitted: 30 items]", plans]


def test_a_short_result_is_never_stubbed():
    log = Log()
    log.user("status")
    log.exchange("a__status", {}, "Quote qt-1 is paid.")
    log.compaction(0, "", pruned_before=99)
    assert messages.render(log.events, "s")[-1]["content"] == "Quote qt-1 is paid."


def test_a_stub_says_how_much_was_left_out():
    assert messages.stub('[{"a": 1}, {"a": 2}]') == "[result omitted: 2 items]"
    assert messages.stub("x" * 900) == "[result omitted: 900 characters]"
    assert messages.stub("Header:\na\nb\nc\nd") == "[result omitted: 4 items]"
