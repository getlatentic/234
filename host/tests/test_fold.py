# SPDX-License-Identifier: AGPL-3.0-or-later
from turns import fold, kinds
from turns.eventlog import Event


def ev(seq, type, payload=None, task=None, ref=None):
    return Event(seq, type, task, ref, payload or {}, 0)


def reply(seq, text="", calls=(), upto=0, message="m"):
    payload = {"message": message, "text": text, "finish_reason": "stop", "upto": upto}
    if calls:
        payload["tool_calls"] = list(calls)
    return ev(seq, kinds.ASSISTANT, payload)


CALL = {"id": "c1", "name": "s__make", "arguments": "{}"}
RESULT = ev(3, kinds.TOOL, {"call_id": "c1", "result_text": "made it", "tool": "make", "is_error": False})


def test_nothing_to_do_on_an_empty_log_or_after_an_answer():
    assert fold.next_action([]) == fold.Idle()
    events = [ev(1, kinds.USER, {"text": "hi"}), reply(2, "hello", upto=1)]
    assert fold.next_action(events) == fold.Idle()


def test_an_unanswered_input_asks_for_a_model_round():
    events = [ev(1, kinds.USER, {"text": "hi"})]
    assert fold.next_action(events) == fold.ModelRound(events[0])


def test_a_card_note_alone_does_not_ask_for_a_reply():
    events = [
        ev(1, kinds.USER, {"text": "hi"}),
        reply(2, "hello", upto=1),
        ev(3, kinds.CARD_CONTEXT, {"text": "x"}),
    ]
    assert fold.next_action(events) == fold.Idle()


def test_calls_without_results_are_run_before_anything_else():
    events = [ev(1, kinds.USER, {"text": "pay"}), reply(2, "", [CALL], upto=1)]
    action = fold.next_action(events)
    assert isinstance(action, fold.ToolRound) and action.calls == [CALL]


def test_when_every_result_is_in_the_model_is_asked_again():
    events = [ev(1, kinds.USER, {"text": "pay"}), reply(2, "", [CALL], upto=1), RESULT]
    assert fold.next_action(events) == fold.ModelRound(RESULT)


def test_a_message_that_came_in_while_the_model_streamed_is_answered_by_the_next_round():
    events = [
        ev(1, kinds.USER, {"text": "first"}),
        ev(2, kinds.USER, {"text": "second"}),
        reply(3, "answer to the first", upto=1),
    ]
    assert fold.next_action(events) == fold.ModelRound(events[1])


def test_the_open_turn_and_the_task_waiting_for_the_person():
    started = ev(2, kinds.TURN_STARTED, {"task": "t1"})
    finished = ev(5, kinds.TURN_FINISHED, {"task": "t1", "reason": kinds.INPUT_REQUIRED})
    assert fold.open_turn([ev(1, kinds.USER), started]) == started
    assert fold.open_turn([started, finished]) is None
    assert fold.waiting_task([started, finished]) == "t1"
    assert fold.waiting_task([started, finished, ev(6, kinds.TURN_STARTED, {"task": "t2"})]) is None


def quote_event(seq, type, phase, task="t1"):
    result = {"structuredContent": {"quote": {"id": "q", "phase": phase}}}
    return ev(seq, type, {"result": result}, task=task, ref="q")


def test_a_card_awaits_approval_until_a_pushed_state_says_otherwise():
    card = quote_event(1, kinds.CARD, "awaiting_approval")
    assert fold.cards_awaiting_approval([card], "t1")
    assert not fold.cards_awaiting_approval([card, quote_event(2, kinds.CARD_STATE, "succeeded")], "t1")
    assert not fold.cards_awaiting_approval([card], "other")


def test_task_state_follows_the_turns_of_the_task():
    user = ev(1, kinds.USER, task="t")
    started = ev(2, kinds.TURN_STARTED, {"task": "t"}, task="t")

    def finished(reason):
        return ev(9, kinds.TURN_FINISHED, {"task": "t", "reason": reason}, task="t")

    assert fold.task_state([user]) == "submitted"
    assert fold.task_state([user, started]) == "working"
    assert fold.task_state([user, started, finished(kinds.COMPLETED)]) == "completed"
    assert fold.task_state([user, started, finished(kinds.INPUT_REQUIRED)]) == "input_required"
    assert fold.task_state([user, started, finished(kinds.FAILED)]) == "failed"
    assert fold.task_state([user, started, finished(kinds.MAX_ROUNDS)]) == "failed"
    resumed = [user, started, finished(kinds.INPUT_REQUIRED), started]
    assert fold.task_state(resumed) == "working"
    again = ev(10, kinds.USER, task="t")
    assert fold.task_state([user, started, finished(kinds.INPUT_REQUIRED), again]) == "submitted"
