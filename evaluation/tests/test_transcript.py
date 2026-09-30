# SPDX-License-Identifier: AGPL-3.0-or-later
from evaluation.transcript import turns_of


def event(seq, type_, payload, at=1000):
    return {"seq": seq, "type": type_, "task": "t", "ref": None, "payload": payload, "at": at + seq * 100}


def chat():
    quote = {
        "result": {
            "structuredContent": {
                "quote": {
                    "id": "q1",
                    "details": {"kind": "airtime"},
                    "amount": {"kobo": 50000},
                    "merchant": "MTN",
                }
            }
        },
        "tool": "create_airtime_quote",
    }
    tool = {
        "call_id": "c1",
        "server": "airtime",
        "tool": "create_airtime_quote",
        "arguments": {"phone": "0803"},
        "result_text": "Quote ready",
        "is_error": False,
    }
    twin = {**tool, "call_id": "c2", "result_text": "Not made again: Quote ready"}
    return [
        event(1, "user", {"text": "Buy airtime"}),
        event(2, "turn.started", {"task": "t"}),
        event(3, "text", {"message": "m", "text": "Sure"}),
        event(
            4,
            "assistant",
            {
                "message": "m",
                "text": "Sure",
                "finish_reason": "tool_calls",
                "tool_calls": [{"id": "c1", "name": "airtime__create_airtime_quote"}],
            },
        ),
        event(5, "tool", tool),
        event(6, "tool", twin),
        event(7, "card", quote),
        event(8, "assistant", {"message": "n", "text": "Press Approve.", "finish_reason": "stop"}),
        event(9, "turn.finished", {"task": "t", "reason": "input_required"}),
        event(10, "user", {"text": "thanks"}),
        event(11, "assistant", {"message": "o", "text": "You're welcome.", "finish_reason": "stop"}),
        event(12, "turn.finished", {"task": "u", "reason": "completed"}),
    ]


def test_each_user_message_starts_a_turn():
    first, second = turns_of(chat())
    assert (first["say"], second["say"]) == ("Buy airtime", "thanks")
    assert first["end"] == "input_required" and second["end"] == "completed"


def test_a_turn_holds_its_calls_cards_reply_and_finish_reasons():
    first, second = turns_of(chat())
    assert [c["repeated"] for c in first["calls"]] == [False, True]
    assert first["cards"] == [
        {
            "tool": "create_airtime_quote",
            "quote_id": "q1",
            "kind": "airtime",
            "amount_kobo": 50000,
            "merchant": "MTN",
            "menu_items": None,
        }
    ]
    assert first["reply"] == "Sure Press Approve."
    assert first["finish_reasons"] == ["tool_calls", "stop"]
    assert second["calls"] == [] and second["reply"] == "You're welcome."


def test_latency_runs_from_the_message_to_the_end_of_the_turn():
    first, second = turns_of(chat())
    assert first["latency_ms"] == 800 and second["latency_ms"] == 200


def test_a_turn_that_never_finished_says_so():
    (only,) = turns_of(chat()[:5])
    assert only["end"] == "unfinished" and only["latency_ms"] is None
