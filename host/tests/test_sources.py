# SPDX-License-Identifier: AGPL-3.0-or-later
"""Answering from sources (turns/sources.py): a turn may search a few times, makes no change once it has read
a source, hears the passages of an earlier question only as a stub, and has the links and amounts of its
answer checked against what it read."""

import json

import pytest

from turns import kinds, sources
from turns.chat_core import ChatCore
from turns.settings import Settings

from .support import FakeAlarms, FakeHub, FakeSockets, ScriptedModel, tool_call
from .test_metrics import settle

SEARCH, SEND, STATUS = "knowledge__search_knowledge", "s__send", "s__status"
PASSAGE = {
    "passage_id": "frsc-licence#0",
    "source_id": "frsc-licence",
    "text": "The fee is 15,000 naira. See https://frsc.gov.ng/fees",
}
FOUND = {
    "content": [{"type": "text", "text": "[1] FRSC https://frsc.gov.ng/fees\n> The fee is 15,000 naira."}],
    "structuredContent": {"untrusted": True, "passages": [PASSAGE]},
}
NOTHING = {"content": [{"type": "text", "text": "No source says anything about that."}]}


def core(chat, sql, clock, *script, results=None, **changes):
    hub = FakeHub(
        {SEARCH: FOUND, SEND: {"content": [{"type": "text", "text": "sent"}]},
         STATUS: {"content": [{"type": "text", "text": "ok"}]}, **(results or {})},
        card_uri=None,
    )  # fmt: skip
    hub.read_only_tools = {STATUS, SEARCH}
    settings = Settings(mcp_url="x", llm_base_url="m", llm_api_key="k", **changes)
    model = ScriptedModel(*script)
    return ChatCore(chat.id, sql, settings, model, hub, FakeSockets(), FakeAlarms(), clock), hub, model


async def ask(made, text):
    await made.submit(kinds.USER, text)
    await settle(made)


async def events_of(made):
    return await made.log.context()


def tool_events(events):
    return [e.payload for e in events if e.type == kinds.TOOL]


def notices(events):
    return [e.payload["text"] for e in events if e.type == kinds.NOTICE]


def test_a_link_or_an_amount_the_turn_did_not_read_or_hear_is_named():
    read = "The fee is 15,000 naira. See https://frsc.gov.ng/fees."
    assert sources.ungrounded("It costs ₦15,000: https://frsc.gov.ng/fees", read, "") == []
    assert sources.ungrounded("It costs ₦20,000.", read, "") == ["₦20,000"]
    assert sources.ungrounded("Go to https://scam.example.com/pay", read, "") == [
        "https://scam.example.com/pay"
    ]
    assert sources.ungrounded("It is N15000.00 naira, so 15,000 naira", read, "") == []
    assert sources.ungrounded("Paying ₦5,000 as you said", read, "send 5,000 to Ada") == []
    assert sources.ungrounded("No figure or link here.", "", "") == []


async def test_a_turn_that_keeps_searching_is_stopped_and_answers(chat, sql, clock):
    searches = [("", [tool_call(SEARCH, {"query": "fee"}, f"c{i}")]) for i in range(4)]
    made, hub, _ = core(
        chat, sql, clock, *searches, "The fee is 15,000 naira.", searches_per_turn=3, max_tool_rounds=8
    )
    await ask(made, "what is the fee")
    run = tool_events(await events_of(made))
    assert [c for _, c in hub.calls] == [{"query": "fee"}] * 3
    assert [t["code"] for t in run if t["is_error"]] == ["SEARCH_BUDGET"]


async def test_nothing_that_changes_something_is_called_once_a_source_has_been_read(chat, sql, clock):
    made, hub, _ = core(
        chat, sql, clock,
        ("", [tool_call(SEARCH, {"query": "fee"}, "c1")]),
        ("", [tool_call(SEND, {"amount": 1}, "c2"), tool_call(STATUS, {}, "c3")]),
        "Done.",
    )  # fmt: skip
    await ask(made, "what is the fee")
    run = {t["tool"]: t for t in tool_events(await events_of(made))}
    assert run["send"]["code"] == "AFTER_SOURCES" and run["status"]["is_error"] is False
    assert [name for name, _ in hub.calls] == [SEARCH, STATUS]


async def test_the_next_message_of_the_person_lifts_it(chat, sql, clock):
    made, hub, _ = core(
        chat, sql, clock,
        ("", [tool_call(SEARCH, {"query": "fee"}, "c1")]), "It is 15,000 naira.",
        ("", [tool_call(SEND, {"amount": 1}, "c2")]), "Sent.",
    )  # fmt: skip
    await ask(made, "what is the fee")
    await ask(made, "send 1 naira to Ada")
    assert [name for name, _ in hub.calls] == [SEARCH, SEND]


async def test_a_search_that_failed_does_not_stop_a_payment(chat, sql, clock):
    made, hub, _ = core(
        chat, sql, clock,
        ("", [tool_call(SEARCH, {}, "c1")]), ("", [tool_call(SEND, {}, "c2")]), "Done.",
        results={SEARCH: {"isError": True, "content": [{"type": "text", "text": "INTERNAL: down"}]}},
    )  # fmt: skip
    await ask(made, "fee and send")
    assert [name for name, _ in hub.calls] == [SEARCH, SEND]


async def test_the_passages_of_an_earlier_question_are_sent_as_a_stub_and_this_ones_in_full(chat, sql, clock):
    made, _, model = core(
        chat, sql, clock,
        ("", [tool_call(SEARCH, {"query": "fee"}, "c1")]), "It is 15,000 naira.",
        ("", [tool_call(SEARCH, {"query": "fee again"}, "c2")]), "Still 15,000 naira.",
    )  # fmt: skip
    await ask(made, "what is the fee")
    await ask(made, "and again?")
    last = json.dumps(model.sent[-1])
    assert last.count("The fee is 15,000 naira.") == 1 and sources.ELIDED in last


async def test_a_retrieval_is_logged_without_the_question_or_the_text(chat, sql, clock, caplog):
    import logging

    caplog.set_level(logging.INFO)
    made, _, _ = core(
        chat, sql, clock, ("", [tool_call(SEARCH, {"query": "my secret question"}, "c1")]), "Ok."
    )
    await ask(made, "what is the fee")
    (line,) = [r for r in caplog.records if r.getMessage() == "retrieval"]
    assert line.fields == {"tool": "search_knowledge", "passages": 1, "sources": ["frsc-licence"]}
    assert "secret question" not in caplog.text


async def test_an_answer_with_an_amount_or_link_nobody_gave_is_named_to_the_person(chat, sql, clock):
    made, _, _ = core(
        chat, sql, clock,
        ("", [tool_call(SEARCH, {"query": "fee"}, "c1")]),
        "The fee is 15,000 naira, or 20,000 naira at https://scam.example.com/pay.",
    )  # fmt: skip
    await ask(made, "what is the fee")
    assert notices(await events_of(made)) == [
        sources.NOT_IN_SOURCES.format(items="https://scam.example.com/pay, ₦20,000")
    ]


async def test_a_grounded_answer_and_a_turn_that_never_searched_get_no_notice(chat, sql, clock):
    made, _, _ = core(
        chat, sql, clock, ("", [tool_call(SEARCH, {}, "c1")]), "It is 15,000 naira. https://frsc.gov.ng/fees"
    )
    await ask(made, "fee?")
    plain, _, _ = core(chat, sql, clock, "Airtime costs 100 naira at https://example.com")
    await ask(plain, "hi")
    assert notices(await events_of(made)) == [] and notices(await events_of(plain)) == []


def test_only_the_knowledge_server_is_a_source():
    assert sources.is_source("knowledge__search_knowledge") and not sources.is_source("memory__recall")


@pytest.mark.parametrize("budget", [1, 2])
async def test_the_budget_is_a_setting(chat, sql, clock, budget):
    searches = [("", [tool_call(SEARCH, {"query": "q"}, f"c{i}")]) for i in range(3)]
    made, hub, _ = core(chat, sql, clock, *searches, "Done.", searches_per_turn=budget, max_tool_rounds=8)
    await ask(made, "q")
    assert len(hub.calls) == budget
