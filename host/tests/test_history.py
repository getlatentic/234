# SPDX-License-Identifier: AGPL-3.0-or-later
from chat import history
from turns import kinds
from turns.eventlog import Event


def ev(seq, type, payload=None, ref=None, task=None):
    return Event(seq, type, task, ref, payload or {}, 0)


def test_streamed_text_shows_as_one_open_bubble_until_its_reply_lands():
    events = [
        ev(1, kinds.TEXT, {"message": "m", "text": "Hel"}),
        ev(2, kinds.TEXT, {"message": "m", "text": "lo"}),
    ]
    [item] = history.items(events)
    assert (item.kind, item.text, item.streaming) == (kinds.ASSISTANT, "Hello", True)
    events.append(ev(3, kinds.ASSISTANT, {"message": "m", "text": "Hello there"}))
    [item] = history.items(events)
    assert (item.text, item.streaming) == ("Hello there", False)


def test_an_aborted_reply_and_an_empty_one_leave_nothing():
    events = [
        ev(1, kinds.TEXT, {"message": "m", "text": "Let me"}),
        ev(2, kinds.ROUND_ABORTED, {"message": "m"}),
        ev(3, kinds.ASSISTANT, {"message": "n", "text": " ", "tool_calls": [{"id": "c"}]}),
    ]
    assert history.items(events) == []


def test_a_card_carries_the_latest_state_pushed_for_its_quote():
    card = ev(1, kinds.CARD, {"result": {"a": 1}}, ref="q")
    first = ev(2, kinds.CARD_STATE, {"result": {"phase": "one"}}, ref="q")
    second = ev(3, kinds.CARD_STATE, {"result": {"phase": "two"}}, ref="q")
    stray = ev(4, kinds.CARD_STATE, {"result": {"phase": "x"}}, ref="unknown")
    [item] = history.items([card, first, second, stray])
    assert item.kind == kinds.CARD and item.state == {"phase": "two"}


def test_turn_bookkeeping_is_not_shown_and_a_turn_can_be_working():
    events = [ev(1, kinds.TURN_STARTED, {"task": "t"}), ev(2, kinds.TURN_RESUMED, {"task": "t"})]
    assert history.items(events) == [] and history.is_working(events)
    assert not history.is_working([*events, ev(3, kinds.TURN_FINISHED, {"task": "t"})])


def test_a_card_note_is_shown_as_what_the_card_now_shows():
    [item] = history.items(
        [ev(1, kinds.CARD_CONTEXT, {"text": "Card for qt-1 now shows: Payment received. Thanks."})]
    )
    assert item.note == "Payment received. Thanks"


def tool(seq, is_error=False, cancelled=False):
    return ev(
        seq, kinds.TOOL, {"tool": "t", "is_error": is_error, **({"cancelled": True} if cancelled else {})}
    )


def test_a_stored_tool_row_starts_quiet_and_says_a_word_only_when_the_call_did_not_work():
    worked, refused, stopped = history.items([tool(1), tool(2, True), tool(3, True, True)])
    assert [(i.tool_state, i.tool_state_word) for i in (worked, refused, stopped)] == [
        ("ok", ""),
        ("refused", "refused"),
        ("stopped", "stopped"),
    ]


def compaction(seq, trigger="auto", summary="## Done\n- paid"):
    return ev(
        seq, kinds.COMPACTION, {"trigger": trigger, "summary": summary, "covers": {"first": 1, "last": 3}}
    )


def test_history_is_shown_whole_and_only_the_latest_compaction_is_marked_where_it_sits():
    events = [
        ev(1, kinds.USER, {"text": "one"}),
        compaction(2, summary="first"),
        ev(3, kinds.USER, {"text": "two"}),
        compaction(4, summary="second"),
        ev(5, kinds.USER, {"text": "three"}),
    ]
    shown = history.items(events)
    assert [i.kind for i in shown] == [kinds.USER, kinds.USER, kinds.COMPACTION, kinds.USER]
    assert [i.event.payload.get("text") for i in shown if i.kind == kinds.USER] == ["one", "two", "three"]
    assert shown[2].compaction_summary == "second"


def test_a_summarised_line_opens_onto_the_summary_and_a_fallback_has_none_to_show():
    [summarised] = history.items([compaction(1)])
    assert summarised.compaction_line == "Earlier messages were summarised"
    assert summarised.compaction_summary == "## Done\n- paid"
    [left_out] = history.items([compaction(1, trigger="fallback")])
    assert left_out.compaction_line == "Earlier messages were left out" and left_out.compaction_summary == ""
