# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio

import pytest

from turns import kinds
from turns.chat_core import ChatCore
from turns.hub import HubError
from turns.settings import Settings

from .card_support import LISTING
from .support import FakeAlarms, FakeHub, FakeSockets, ScriptedModel, quote_result, tool_call

MAKE = "s__make"


class Core:
    def __init__(self, chat, sql, clock, model, hub=None, **changes):
        self.pool, self.alarms = FakeSockets(), FakeAlarms()
        settings = Settings(mcp_url="x", llm_base_url="m", llm_api_key="k", **changes)
        self.hub = hub or FakeHub({MAKE: quote_result()})
        self.core = ChatCore(chat.id, sql, settings, model, self.hub, self.pool, self.alarms, clock)

    async def settle(self):
        while self.core.running:
            await asyncio.sleep(0)
            await self.core._driver

    async def types(self):
        return [e.type for e in await self.core.log.read()]


@pytest.fixture
def core(chat, sql, clock):
    def make(model, hub=None, **changes):
        return Core(chat, sql, clock, model, hub, **changes)

    return make


async def test_submit_records_the_input_and_the_turn_runs_behind_it(core):
    c = core(ScriptedModel("Hello"))
    answer = await c.core.submit(kinds.USER, "hi")
    assert answer["seq"] == 1 and answer["task"]
    await c.settle()
    assert await c.types() == ["user", "turn.started", "text", "assistant", "turn.finished"]


async def test_a_refused_input_is_never_stored(core):
    c = core(ScriptedModel("x"))
    for text, code in (("", "empty"), ("4242 4242 4242 4242", "card_data"), ("x" * 501, "too_long")):
        assert (await c.core.submit(kinds.USER, text))["error"] == code
    assert await c.types() == []
    assert not c.core.running


async def test_the_watchdog_is_armed_while_a_turn_runs_and_cleared_when_it_ends(core):
    c = core(ScriptedModel("Hello"))
    await c.core.submit(kinds.USER, "hi")
    await asyncio.sleep(0)
    await c.settle()
    assert c.alarms.at is None


async def test_a_second_message_during_a_turn_is_answered_without_a_second_loop(core):
    gate = asyncio.Event()

    class Held(ScriptedModel):
        async def stream(self, messages, tools):
            if not self.sent:
                await gate.wait()
            async for piece in super().stream(messages, tools):
                yield piece

    c = core(Held("one", "two"))
    first = await c.core.submit(kinds.USER, "a")
    await asyncio.sleep(0)
    second = await c.core.submit(kinds.USER, "b")
    assert second["task"] == first["task"]
    gate.set()
    await c.settle()
    assert (await c.types()).count("turn.started") == 1
    assert [e.payload["text"] for e in await c.core.log.read() if e.type == kinds.ASSISTANT] == [
        "one ",
        "two ",
    ]


async def test_a_socket_attached_at_a_cursor_gets_what_it_missed_then_the_rest_live(core):
    c = core(ScriptedModel("one two three"))
    await c.core.submit(kinds.USER, "hi")
    await c.settle()
    late = c.pool.open("late")
    await c.core.attach(late, 2)
    assert c.pool.seqs(late) == [3, 4, 5]
    await c.core.submit(kinds.USER, "again")
    await asyncio.sleep(0)
    assert c.pool.seqs(late)[3:5] == [6, 7]


async def test_every_attached_socket_sees_the_same_events_in_order_without_gaps(core):
    c = core(ScriptedModel(("", [tool_call(MAKE, {})]), "Check the card."))
    a, b = c.pool.open("a"), c.pool.open("b")
    await c.core.attach(a, 0)
    await c.core.attach(b, 0)
    await c.core.submit(kinds.USER, "pay")
    await c.settle()
    stored = [e.seq for e in await c.core.log.read()]
    assert c.pool.seqs(a) == c.pool.seqs(b) == stored == list(range(1, len(stored) + 1))


async def test_a_socket_that_has_not_said_where_to_start_is_sent_nothing(core):
    c = core(ScriptedModel("Hello"))
    quiet = c.pool.open("quiet")
    await c.core.submit(kinds.USER, "hi")
    await c.settle()
    assert c.pool.frames[quiet] == []


async def test_a_cursor_past_the_end_of_the_log_is_told_to_start_over(core):
    c = core(ScriptedModel("x"))
    lost = c.pool.open("lost")
    await c.core.attach(lost, 99)
    assert c.pool.frames[lost] == [{"reset": True}]


async def test_a_socket_that_is_behind_when_an_event_arrives_catches_up_without_repeats(core):
    c = core(ScriptedModel("x"))
    a = c.pool.open("a")
    for text in ("one", "two", "three"):
        await c.core.log.append(kinds.NOTICE, {"level": "info", "text": text})
    c.pool.cursor[a] = 1
    await c.core.log.append(kinds.NOTICE, {"level": "info", "text": "four"})
    assert c.pool.seqs(a) == [2, 3, 4]


async def card_chat(core, hub=None):
    c = core(ScriptedModel(("", [tool_call(MAKE, {})]), "Check the card."), hub)
    await c.core.submit(kinds.USER, "pay")
    await c.settle()
    return c


async def test_a_cards_call_reaches_the_connector_and_a_changed_quote_is_pushed_to_every_client(core):
    hub = FakeHub({MAKE: quote_result(), "s__approve": quote_result("awaiting_checkout", token=None)})
    hub.app = {"approve_quote": quote_result("awaiting_checkout", token=None)}

    async def call_app_tool(server, name, arguments, owner, account=False):
        return hub.app[name]

    async def tools(server):
        return LISTING[server]

    hub.call_app_tool = call_app_tool
    hub.tools = tools
    c = await card_chat(core, hub)
    a = c.pool.open("a")
    await c.core.attach(a, 0)
    result = await c.core.card_call("s", "approve_quote", {"quote_id": "qt-1"})
    assert result["structuredContent"]["quote"]["phase"] == "awaiting_checkout"
    state = [e for e in await c.core.log.read() if e.type == kinds.CARD_STATE]
    assert len(state) == 1 and state[0].ref == "qt-1" and "_meta" not in state[0].payload["result"]
    assert state[0].seq in c.pool.seqs(a)
    await c.core.card_call("s", "approve_quote", {"quote_id": "qt-1"})
    assert len([e for e in await c.core.log.read() if e.type == kinds.CARD_STATE]) == 1


async def test_a_card_call_the_person_makes_has_no_tool_deadline(core):
    hub = FakeHub({MAKE: quote_result()})

    async def call_app_tool(server, name, arguments, owner, account=False):
        await asyncio.sleep(0.05)
        return quote_result("awaiting_checkout", token=None)

    async def tools(server):
        return LISTING[server]

    hub.call_app_tool, hub.tools = call_app_tool, tools
    c = await card_chat(lambda model, hub: core(model, hub, tool_deadline_seconds=0.01), hub)
    result = await c.core.card_call("s", "approve_quote", {"quote_id": "qt-1"})
    assert result["structuredContent"]["quote"]["phase"] == "awaiting_checkout"


async def test_a_card_can_only_act_on_a_quote_of_this_chat_and_the_server_that_made_it(core):
    c = await card_chat(core)
    with pytest.raises(HubError, match="no card"):
        await c.core.card_call("s", "approve_quote", {"quote_id": "qt-someone-else"})
    with pytest.raises(HubError, match="no card"):
        await c.core.card_call("other", "approve_quote", {"quote_id": "qt-1"})


async def test_a_webhook_refreshes_the_card_with_the_connectors_own_answer(core):
    c = await card_chat(core)

    async def call_app_tool(server, name, arguments, owner, account=False):
        assert (name, arguments) == ("verify_quote", {"quote_id": "qt-1"})
        return quote_result("succeeded", token=None)

    c.hub.call_app_tool = call_app_tool
    a = c.pool.open("a")
    await c.core.attach(a, 0)
    assert await c.core.refresh_card("qt-1") is True
    pushed = [f for f in c.pool.frames[a] if f.get("type") == kinds.CARD_STATE]
    assert pushed[0]["payload"]["result"]["structuredContent"]["quote"]["phase"] == "succeeded"
    assert await c.core.refresh_card("qt-unknown") is False


async def test_a_note_from_a_card_is_kept_and_starts_no_turn(core):
    c = core(ScriptedModel("x"))
    await c.core.note("The card now shows: paid.")
    await asyncio.sleep(0)
    assert await c.types() == ["card_context"] and not c.core.running


async def test_the_same_note_from_two_tabs_is_kept_once(core):
    c = core(ScriptedModel("x"))
    first = await c.core.note("The card now shows: paid.")
    again = await c.core.note("The card now shows: paid.")
    other = await c.core.note("The card now shows: refunded.")
    assert again == first and other["seq"] == first["seq"] + 1
    assert await c.types() == ["card_context", "card_context"]


async def test_a_note_the_log_already_holds_is_not_added_again_after_others(core):
    c = core(ScriptedModel("x"))
    first = await c.core.note("Quote q1 now shows: expired.")
    await c.core.note("Quote q2 now shows: declined.")
    again = await c.core.note("Quote q1 now shows: expired.")
    assert again == first
    assert await c.types() == ["card_context", "card_context"]


async def interrupt_after_streaming(c, sql_events):
    """The state a restart leaves: a turn started, part of a reply streamed, nothing else."""
    log = c.core.log
    await log.append(kinds.USER, {"text": "pay"}, task="t1")
    await log.append(kinds.TURN_STARTED, {"task": "t1", "trigger": 1}, task="t1")
    await log.append(kinds.TEXT, {"message": "m1", "text": "Let me"}, task="t1")


async def test_the_watchdog_resumes_a_turn_the_object_lost_and_discards_its_half_reply(core):
    c = core(ScriptedModel("Here is the answer"))
    await interrupt_after_streaming(c, None)
    await c.core.on_alarm()
    await c.settle()
    types = await c.types()
    assert types[3:5] == ["round.aborted", "turn.resumed"]
    assert types[-1] == "turn.finished"
    assert [e.payload["text"] for e in await c.core.log.read() if e.type == kinds.ASSISTANT] == [
        "Here is the answer "
    ]


async def test_the_watchdog_leaves_an_idle_chat_alone_and_only_rearms_a_live_loop(core, clock):
    c = core(ScriptedModel("Hello"))
    await c.core.on_alarm()
    assert await c.types() == [] and c.alarms.at is None
    await c.core.submit(kinds.USER, "hi")
    await c.settle()
    before = len(await c.types())
    await c.core.on_alarm()
    assert len(await c.types()) == before


async def test_purge_erases_the_log_and_stops_the_turn(core):
    c = core(ScriptedModel("one two three four"))
    await c.core.submit(kinds.USER, "hi")
    await c.core.purge()
    await asyncio.sleep(0)
    assert await c.core.log.read() == [] and not c.core.running


async def test_a_chat_moved_to_an_account_while_its_object_is_alive_is_spent_for_by_the_new_owner(
    core, chat, sql
):
    from accounts.owner import account_owner
    from turns.ledger_owner import ledger_owner

    c = core(ScriptedModel("x"))
    before = await c.core._ledger_owner()
    assert before == ledger_owner("v:a")
    moved = account_owner("uid-abc", "key")
    await sql.execute("UPDATE chat_chat SET owner = ? WHERE id = ?", moved, chat.id)
    assert await c.core._ledger_owner() == ledger_owner(moved) != before


async def test_a_turn_after_the_chat_moved_to_an_account_is_the_accounts_with_its_notes(core, chat, sql):
    from accounts.owner import account_owner
    from turns.ledger_owner import ledger_owner

    from .memory_support import MemoryHub

    hub = MemoryHub()
    c = core(ScriptedModel("one", "two"), hub)
    await c.core.submit(kinds.USER, "first")
    await c.settle()
    assert hub.calls == []
    moved = account_owner("uid-abc", "key")
    await sql.execute("UPDATE chat_chat SET owner = ? WHERE id = ?", moved, chat.id)
    await c.core.submit(kinds.USER, "second")
    await c.settle()
    assert hub.owners == [ledger_owner(moved)] and hub.index_calls() == 1
    assert c.core._model.sent[1][1]["content"].startswith("What this person asked 234 to remember.")
