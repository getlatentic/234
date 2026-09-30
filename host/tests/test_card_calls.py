# SPDX-License-Identifier: AGPL-3.0-or-later
"""A menu card ordering: the search is recorded as a card of its own, the card's order opens the approval
card in the log once, the card that asked is told, and the model gets a note with no token in it."""

import asyncio
import json

import pytest

from a2a import wire
from turns import fold, kinds, messages
from turns.chat_core import ChatCore
from turns.hub import HubError
from turns.settings import Settings

from .card_support import APPROVAL, CARD_ID, MAKE, MENU, SEARCH, CardHub, menu_result, ordered
from .support import FakeAlarms, FakeSockets, ScriptedModel, tool_call

ORDER = {"card_id": CARD_ID, "items": [{"item_id": "zobo", "quantity": 2}], "delivery_area": "Yaba"}


class Rig:
    def __init__(self, chat, sql, clock, hub, model):
        self.pool = FakeSockets()
        settings = Settings(mcp_url="x", llm_base_url="m", llm_api_key="k")
        self.hub, self.model = hub, model
        self.core = ChatCore(chat.id, sql, settings, model, hub, self.pool, FakeAlarms(), clock)

    async def ask_for_the_menu(self):
        await self.core.submit(kinds.USER, "what is on the menu")
        while self.core.running:
            await asyncio.sleep(0)
            await self.core._driver

    async def events(self, type=None):
        return [e for e in await self.core.log.read() if type is None or e.type == type]


@pytest.fixture
def rig(chat, sql, clock):
    def make(app=None, **hub):
        model = ScriptedModel(("", [tool_call(SEARCH, {})]), "Pick what you like on the card.")
        hub = CardHub(
            {SEARCH: menu_result(), MAKE: ordered("qt-1")}, app or {"order_from_menu": ordered()}, **hub
        )
        return Rig(chat, sql, clock, hub, model)

    return make


async def test_the_menu_search_is_a_card_named_by_its_own_id(rig):
    r = rig()
    await r.ask_for_the_menu()
    [card] = await r.events(kinds.CARD)
    assert card.ref == CARD_ID and card.payload["resource_uri"] == MENU and card.task
    assert card.payload["result"]["structuredContent"]["merchant"] == "Mama Put"


async def test_the_model_reads_the_search_as_its_text_only(rig):
    r = rig()
    await r.ask_for_the_menu()
    tool = next(m for m in r.model.sent[-1] if m["role"] == "tool")
    assert tool["content"] == "Mama Put: 11 items match. The card shows them."
    assert "zobo" not in json.dumps(r.model.sent[-1]) and "card_id" not in json.dumps(r.model.sent[-1])


async def test_an_order_from_the_menu_opens_the_approval_card_in_the_log(rig):
    r = rig()
    await r.ask_for_the_menu()
    before = len(await r.events())
    told = await r.core.card_call("s", "order_from_menu", ORDER)
    new = (await r.events())[before:]
    assert [e.type for e in new] == [kinds.CARD, kinds.CARD_STATE, kinds.CARD_CONTEXT]
    opened, state, note = new
    assert opened.ref == "qt-9" and opened.payload["resource_uri"] == APPROVAL and opened.task is None
    assert opened.payload["server"] == "s" and opened.payload["tool"] == "order_from_menu"
    assert opened.payload["result"]["_meta"] == {"approvalToken": "tok-menu-order"}
    assert state.ref == CARD_ID and state.payload["result"] == told
    assert told["structuredContent"] == {"spawned": {"ref": "qt-9"}}
    assert note.task is None


async def test_the_card_that_asked_is_never_given_the_token_or_the_quote(rig):
    r = rig()
    await r.ask_for_the_menu()
    told = await r.core.card_call("s", "order_from_menu", ORDER)
    assert (
        "tok-menu-order" not in json.dumps(told) and "_meta" not in told and "quote" not in json.dumps(told)
    )
    [state] = await r.events(kinds.CARD_STATE)
    assert "tok-menu-order" not in json.dumps(state.payload)


async def test_the_model_learns_of_the_order_from_a_note_without_the_token(rig):
    r = rig()
    await r.ask_for_the_menu()
    await r.core.card_call("s", "order_from_menu", ORDER)
    sent = messages.render(await r.core.log.context(), "system")
    notes = [
        m["content"] for m in sent if m["content"] and m["content"].startswith(messages.CARD_UPDATE_PREFIX)
    ]
    assert len(notes) == 1 and "qt-9" in notes[0] and "₦2,000" in notes[0] and "get_quote_status" in notes[0]
    assert "tok-menu-order" not in json.dumps(sent)
    assert not r.core.running and not fold.open_turn(await r.core.log.context())


async def test_the_person_reads_the_short_state_after_now_shows(rig):
    r = rig()
    await r.ask_for_the_menu()
    await r.core.card_call("s", "order_from_menu", ORDER)
    [note] = await r.events(kinds.CARD_CONTEXT)
    assert note.payload["text"].endswith("The card now shows: Order ready to approve")
    assert note.payload["text"].count("now shows: ") == 1


async def test_asking_again_from_another_tab_opens_nothing_twice(rig):
    r = rig()
    await r.ask_for_the_menu()
    first = await r.core.card_call("s", "order_from_menu", ORDER)
    again = await r.core.card_call("s", "order_from_menu", ORDER)
    assert again == first
    assert [len(await r.events(t)) for t in (kinds.CARD, kinds.CARD_STATE, kinds.CARD_CONTEXT)] == [2, 1, 1]


async def test_asking_together_from_many_tabs_opens_one_card(rig):
    r = rig()
    await r.ask_for_the_menu()
    answers = await asyncio.gather(*[r.core.card_call("s", "order_from_menu", ORDER) for _ in range(8)])
    assert all(a == answers[0] for a in answers)
    assert [len(await r.events(t)) for t in (kinds.CARD, kinds.CARD_STATE, kinds.CARD_CONTEXT)] == [2, 1, 1]


async def test_every_client_attached_sees_the_new_card_then_the_menu_cards_state(rig):
    r = rig()
    await r.ask_for_the_menu()
    socket = r.pool.open("a")
    await r.core.attach(socket, 0)
    await r.core.card_call("s", "order_from_menu", ORDER)
    types = [f["type"] for f in r.pool.frames[socket]]
    assert types[-3:] == [kinds.CARD, kinds.CARD_STATE, kinds.CARD_CONTEXT]


async def test_a_refusal_from_the_connector_opens_nothing(rig):
    refusal = {"isError": True, "content": [{"type": "text", "text": "ITEM_UNAVAILABLE: sold out"}]}
    r = rig(app={"order_from_menu": refusal})
    await r.ask_for_the_menu()
    before = len(await r.events())
    assert await r.core.card_call("s", "order_from_menu", ORDER) == refusal
    assert len(await r.events()) == before


async def test_a_card_may_call_only_the_tools_its_own_view_lists(rig):
    r = rig(app={"order_from_menu": ordered(), "approve_quote": ordered("qt-9")})
    await r.ask_for_the_menu()
    with pytest.raises(HubError, match="not a tool of this card"):
        await r.core.card_call("s", "approve_quote", {"card_id": CARD_ID, "approval_token": "x"})
    with pytest.raises(HubError, match="not a tool of this card"):
        await r.core.card_call("s", "nothing", {"card_id": CARD_ID})
    assert r.hub.app_calls == []


async def test_an_approval_card_cannot_make_an_order(rig):
    r = rig()
    await r.core.submit(kinds.USER, "x")
    await r.core.log.append(
        kinds.CARD, {"server": "s", "tool": "make", "resource_uri": APPROVAL, "result": ordered()}, ref="qt-9"
    )
    with pytest.raises(HubError, match="not a tool of this card"):
        await r.core.card_call("s", "order_from_menu", {"card_id": "qt-9"})


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"card_id": "someone-elses"},
        {"card_id": CARD_ID, "quote_id": "qt-1"},
        {"card_id": CARD_ID, "quote_id": CARD_ID},
    ],
    ids=["names no card", "another chat's card", "two different names", "one name twice"],
)
async def test_a_card_must_name_one_card_of_this_chat(rig, arguments):
    r = rig()
    await r.ask_for_the_menu()
    with pytest.raises(HubError):
        await r.core.card_call("s", "order_from_menu", arguments)
    assert r.hub.app_calls == []


async def test_a_card_of_another_server_is_not_this_servers(rig):
    r = rig()
    await r.ask_for_the_menu()
    with pytest.raises(HubError, match="no card"):
        await r.core.card_call("other", "order_from_menu", ORDER)


@pytest.mark.parametrize("uri", ["ui://other/card.html", "https://evil.example/card.html", 7])
async def test_a_result_asking_for_a_card_of_another_server_is_refused(rig, uri):
    bad = ordered()
    bad["_meta"]["ui"]["resourceUri"] = uri
    r = rig(app={"order_from_menu": bad})
    await r.ask_for_the_menu()
    before = len(await r.events())
    with pytest.raises(HubError, match="cannot open"):
        await r.core.card_call("s", "order_from_menu", ORDER)
    assert len(await r.events()) == before


async def test_a_result_asking_for_a_card_with_no_quote_is_refused(rig):
    bad = {"content": [], "structuredContent": {"other": 1}, "_meta": {"ui": {"resourceUri": APPROVAL}}}
    r = rig(app={"order_from_menu": bad})
    await r.ask_for_the_menu()
    with pytest.raises(HubError, match="cannot open"):
        await r.core.card_call("s", "order_from_menu", ORDER)


async def test_an_a2a_caller_sees_nothing_of_the_menu_or_the_order(rig):
    r = rig()
    await r.ask_for_the_menu()
    await r.core.card_call("s", "order_from_menu", ORDER)
    events = await r.events()
    task = next(e.task for e in events if e.type == kinds.USER)
    snapshot = json.dumps(
        wire.snapshot(task, "chat", [e for e in events if e.task == task], "https://h/join/x")
    )
    assert "tok-menu-order" not in snapshot and "qt-9" not in snapshot and "zobo" not in snapshot
    assert fold.task_state([e for e in events if e.task == task]) == "completed"


async def test_the_order_survives_a_restart_because_the_log_holds_both_cards(rig, chat, sql, clock):
    r = rig()
    await r.ask_for_the_menu()
    await r.core.card_call("s", "order_from_menu", ORDER)
    fresh = Rig(chat, sql, clock, r.hub, ScriptedModel("unused"))
    phases = fold.card_phases(await fresh.core.log.context())
    assert set(phases) == {CARD_ID, "qt-9"} and phases["qt-9"] == "awaiting_approval"
    assert await fresh.core.card_call("s", "order_from_menu", ORDER) == {
        "content": [{"type": "text", "text": "Order ready to approve"}],
        "structuredContent": {"spawned": {"ref": "qt-9"}},
    }
