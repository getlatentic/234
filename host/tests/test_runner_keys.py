# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the runner gives the hub for each quote call: a key of the host's making, one per call; a repeat
of a request inside one reply made once; and a call run again after a restart, with the key it had."""

import pytest

from turns.calls import REPEATED
from turns.idempotency import derive_key
from turns.ledger_owner import ledger_owner

from .support import FakeHub, ScriptedModel, quote_result, tool_call
from .test_runner import MAKE, Rig

OWNER = ledger_owner("v:a")


class Crash(BaseException):
    """The process dies: nothing after the connector has answered is recorded."""


class LedgerHub(FakeHub):
    """A connector with a ledger: the same key is answered with the quote it already made."""

    def __init__(self, crash_on_call: int | None = None) -> None:
        super().__init__({MAKE: quote_result()})
        self.keyed_tools = {MAKE}
        self.quotes: dict[str, str] = {}
        self.crash_on_call = crash_on_call

    async def call_model_tool(self, qualified, arguments, owner, key, account=False):
        from turns.hub import ToolOutcome

        outcome = await super().call_model_tool(qualified, arguments, owner, key)
        if outcome.is_error:
            return outcome
        quote = self.quotes.setdefault(key, f"qt-{len(self.quotes) + 1}")
        if len(self.keys) == self.crash_on_call:
            raise Crash
        return ToolOutcome("s", "make", quote_result(quote_id=quote), self.card_uri)


@pytest.fixture
def keyed_rig(chat, sql, clock):
    def make(model, hub=None, **changes):
        return Rig(chat, sql, clock, model, hub or LedgerHub(), **changes)

    return make


async def test_a_quote_call_is_given_a_key_derived_from_its_owner_chat_and_call_id(keyed_rig, chat):
    hub = LedgerHub()
    r = keyed_rig(ScriptedModel(("", [tool_call(MAKE, {"amount": 1}, "call_7")]), "Done."), hub)
    await r.say()
    await r.runner.run()
    assert hub.keys == [derive_key(OWNER, chat.id, "call_7")] and hub.owners == [OWNER]


async def test_two_calls_in_one_reply_each_have_a_key(keyed_rig):
    hub = LedgerHub()
    calls = [tool_call(MAKE, {"amount": 1}, "call_a"), tool_call(MAKE, {"amount": 2}, "call_b")]
    r = keyed_rig(ScriptedModel(("", calls), "Done."), hub)
    await r.say()
    await r.runner.run()
    assert len(hub.keys) == 2 and len(set(hub.keys)) == 2 and len(hub.quotes) == 2


async def test_the_same_request_in_a_later_round_is_a_new_request_with_a_new_key_and_a_new_quote(keyed_rig):
    hub = LedgerHub()
    again = ("", [tool_call(MAKE, {"amount": 1}, "call_2")])
    r = keyed_rig(ScriptedModel(("", [tool_call(MAKE, {"amount": 1}, "call_1")]), again, "Done."), hub)
    await r.say()
    await r.runner.run()
    assert len(set(hub.keys)) == 2 and sorted(hub.quotes.values()) == ["qt-1", "qt-2"]


async def test_a_provider_that_numbers_its_calls_from_zero_in_every_reply_still_gets_a_key_per_call(
    keyed_rig,
):
    hub = LedgerHub()
    same_id = lambda: ("", [tool_call(MAKE, {"amount": 1}, "call_0")])  # noqa: E731
    r = keyed_rig(ScriptedModel(same_id(), same_id(), "Done."), hub)
    await r.say()
    await r.runner.run()
    assert len(hub.calls) == 2 and len(set(hub.keys)) == 2
    assert len({e.payload["call_id"] for e in await r.of("tool")}) == 2


async def test_the_same_call_id_in_another_chat_of_the_same_owner_has_another_key(
    chat, other_chat, sql, clock
):
    keys = []
    for owned in (chat, other_chat):
        hub = LedgerHub()
        r = Rig(owned, sql, clock, ScriptedModel(("", [tool_call(MAKE, {}, "call_1")]), "Done."), hub)
        await r.say()
        await r.runner.run()
        keys += hub.keys
    assert keys[0] != keys[1]


async def test_a_request_made_twice_in_one_reply_is_made_once_and_the_model_is_told(keyed_rig):
    hub = LedgerHub()
    twice = [tool_call(MAKE, {"amount": 1}, "call_a"), tool_call(MAKE, {"amount": 1}, "call_b")]
    model = ScriptedModel(("", twice), "One quote is ready.")
    r = keyed_rig(model, hub)
    await r.say()
    await r.runner.run()
    first, second = await r.of("tool")
    assert len(hub.calls) == 1 and len(await r.of("card")) == 1
    assert second.payload["result_text"] == REPEATED + first.payload["result_text"]
    assert not second.payload["is_error"]
    told = [m["content"] for m in model.sent[1] if m["role"] == "tool"]
    assert told == [first.payload["result_text"], second.payload["result_text"]]


async def test_a_repeat_is_still_a_repeat_when_the_model_sends_a_different_key_each_time(keyed_rig):
    hub = LedgerHub()
    calls = [
        tool_call(MAKE, {"amount": 1, "idempotency_key": "model-one-1"}, "call_a"),
        tool_call(MAKE, {"amount": 1, "idempotency_key": "model-two-2"}, "call_b"),
    ]
    r = keyed_rig(ScriptedModel(("", calls), "Done."), hub)
    await r.say()
    await r.runner.run()
    assert len(hub.calls) == 1


async def test_a_repeat_of_a_refused_request_repeats_the_refusal(keyed_rig):
    refusal = {"isError": True, "content": [{"type": "text", "text": "Invalid arguments"}]}
    hub = LedgerHub()
    hub.results[MAKE] = refusal
    twice = [tool_call(MAKE, {"amount": 1}, "call_a"), tool_call(MAKE, {"amount": 1}, "call_b")]
    r = keyed_rig(ScriptedModel(("", twice), "Sorry."), hub)
    await r.say()
    await r.runner.run()
    first, second = await r.of("tool")
    assert second.payload["is_error"] and second.payload["result_text"].endswith(first.payload["result_text"])


@pytest.mark.parametrize(
    "second",
    [
        tool_call(MAKE, {"amount": 2}, "call_b"),
        tool_call("s__other", {"amount": 1}, "call_b"),
    ],
    ids=["other arguments", "other tool"],
)
async def test_a_different_request_in_the_same_reply_is_made(keyed_rig, second):
    hub = LedgerHub()
    hub.results["s__other"] = quote_result(quote_id="qt-x")
    hub.keyed_tools.add("s__other")
    r = keyed_rig(ScriptedModel(("", [tool_call(MAKE, {"amount": 1}, "call_a"), second]), "Done."), hub)
    await r.say()
    await r.runner.run()
    assert len(hub.calls) == 2 and len(set(hub.keys)) == 2


async def test_a_tool_that_takes_no_key_is_run_each_time_it_is_asked_for(keyed_rig):
    hub = FakeHub({"s__plans": {"content": [{"type": "text", "text": "plans"}]}})
    twice = [
        tool_call("s__plans", {"network": "mtn"}, "call_a"),
        tool_call("s__plans", {"network": "mtn"}, "call_b"),
    ]
    r = keyed_rig(ScriptedModel(("", twice), "Done."), hub)
    await r.say()
    await r.runner.run()
    assert len(hub.calls) == 2


async def test_a_call_run_again_after_a_restart_has_the_key_it_had_and_makes_no_second_quote(
    keyed_rig, chat, sql, clock
):
    hub = LedgerHub(crash_on_call=1)
    model = ScriptedModel(("", [tool_call(MAKE, {"amount": 1}, "call_9")]))
    r = keyed_rig(model, hub)
    await r.say()
    with pytest.raises(Crash):
        await r.runner.run()
    assert not await r.of("tool") and len(hub.quotes) == 1

    restarted = Rig(chat, sql, clock, ScriptedModel("Your quote is ready."), hub)
    await restarted.runner.run(resumed=True)

    assert hub.keys == [derive_key(OWNER, chat.id, "call_9")] * 2
    assert len(hub.quotes) == 1
    assert [e.payload["result_text"] for e in await restarted.of("tool")] == [
        "Quote qt-1 is awaiting_approval."
    ]
    assert len(await restarted.of("card")) == 1
    assert (await restarted.of("turn.finished"))[0].payload["reason"] == "input_required"


async def test_a_restart_in_the_middle_of_a_reply_runs_the_rest_and_a_repeat_stays_a_repeat(
    keyed_rig, chat, sql, clock
):
    hub = LedgerHub(crash_on_call=2)
    calls = [
        tool_call(MAKE, {"amount": 1}, "call_a"),
        tool_call(MAKE, {"amount": 1}, "call_b"),
        tool_call(MAKE, {"amount": 2}, "call_c"),
    ]
    r = keyed_rig(ScriptedModel(("", calls)), hub)
    await r.say()
    with pytest.raises(Crash):
        await r.runner.run()
    assert [e.payload["call_id"] for e in await r.of("tool")] == ["call_a", "call_b"]

    restarted = Rig(chat, sql, clock, ScriptedModel("Two quotes are ready."), hub)
    await restarted.runner.run(resumed=True)

    assert hub.keys == [derive_key(OWNER, chat.id, c) for c in ("call_a", "call_c", "call_c")]
    assert sorted(hub.quotes.values()) == ["qt-1", "qt-2"]
    assert [e.payload["call_id"] for e in await restarted.of("tool")] == ["call_a", "call_b", "call_c"]
