# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whose money a tool call touches is named by the host alone, from the chat's owner as stored: a visitor's
own id, in a header of its own on the way to the connectors. Nothing a browser, a card or the model sends
reaches that header."""

import asyncio
import json

import httpx
import pytest

from chat.models import Access
from turns import kinds
from turns.chat_core import ChatCore
from turns.hub import OWNER_HEADER, Hub, HubError
from turns.ledger_owner import ledger_owner
from turns.settings import Settings

from .card_support import LISTING, CardHub, ordered
from .support import FakeAlarms, FakeHub, FakeSockets, ScriptedModel, quote_result, tool_call

VISITOR = "c0ffee00" * 4
OTHER = "0badf00d" * 4
MAKE = "s__make"
KEY = "k" * 40


class TestTheKeyOfAChatsOwner:
    def test_a_visitors_own_id_is_the_key(self):
        assert ledger_owner(f"v:{VISITOR}") == VISITOR

    def test_an_agent_has_a_stable_key_of_its_own_that_hides_its_name(self):
        key = ledger_owner("a:partner")
        assert key == ledger_owner("a:partner") and len(key) == 32 and "partner" not in key
        assert set(key) <= set("0123456789abcdef") and key != ledger_owner("a:other")

    @pytest.mark.parametrize(
        "odd", [f"v:{VISITOR.upper()}", f"v:{VISITOR}0", "v:short", VISITOR, f"x:{VISITOR}"]
    )
    def test_anything_else_is_hashed_never_passed_through(self, odd):
        assert ledger_owner(odd) != VISITOR and len(ledger_owner(odd)) == 32


SEEN: list[httpx.Request] = []


def handler(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    body = json.loads(request.content)
    result = {
        "tools/list": {"tools": [{"name": "make", "inputSchema": {"type": "object"}}, *LISTING["s"][2:]]},
        "tools/call": {"content": [{"type": "text", "text": "ok"}]},
    }.get(body.get("method"), {})
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": body.get("id"), "result": result})


@pytest.fixture
def hub():
    SEEN.clear()
    return Hub({"s": "http://s/mcp"}, httpx.AsyncClient(transport=httpx.MockTransport(handler)), "bearer")


def calls() -> list[dict]:
    return [
        {"owner": r.headers.get(OWNER_HEADER), "body": json.loads(r.content)}
        for r in SEEN
        if json.loads(r.content).get("method") == "tools/call"
    ]


class TestTheHeaderOnTheWire:
    async def test_a_model_call_and_a_cards_call_each_carry_the_owner_and_nothing_else_does(self, hub):
        await hub.tools("s")
        await hub.call_model_tool("s__make", {"a": 1}, VISITOR, KEY)
        await hub.call_app_tool("s", "approve_quote", {"quote_id": "qt-1"}, VISITOR)
        assert [c["owner"] for c in calls()] == [VISITOR, VISITOR]
        others = [r for r in SEEN if json.loads(r.content).get("method") != "tools/call"]
        assert others and all(OWNER_HEADER not in r.headers for r in others)
        assert all(r.headers["authorization"] == "Bearer bearer" for r in SEEN)

    async def test_what_a_caller_puts_in_the_arguments_never_becomes_the_owner(self, hub):
        sly = {"_meta": {"owner": OTHER}, OWNER_HEADER: OTHER, "owner": OTHER, "quote_id": "qt-1"}
        await hub.tools("s")
        await hub.call_model_tool("s__make", sly, VISITOR, KEY)
        await hub.call_app_tool("s", "approve_quote", sly, VISITOR)
        for sent in calls():
            assert sent["owner"] == VISITOR
            assert set(sent["body"]["params"]) == {"name", "arguments"}
            assert sent["body"]["params"]["arguments"] == sly

    @pytest.mark.parametrize(
        "bad", ["", "v:" + VISITOR, VISITOR.upper(), VISITOR[:-1], VISITOR + "0", "x" * 32]
    )
    async def test_a_key_that_is_not_an_owner_is_refused_before_anything_is_sent(self, hub, bad):
        await hub.tools("s")
        sent_before = len(SEEN)
        with pytest.raises(HubError, match="whose money"):
            await hub.call_app_tool("s", "approve_quote", {}, bad)
        assert (await hub.call_model_tool("s__make", {}, VISITOR, KEY)).text == "ok"
        with pytest.raises(HubError, match="whose money"):
            await hub.call_model_tool("s__make", {}, bad, KEY)
        assert len(SEEN) == sent_before + 1


class Core:
    def __init__(self, chat, sql, clock, model, hub):
        self.hub = hub
        settings = Settings(mcp_url="x", llm_base_url="m", llm_api_key="k", flush_seconds=0)
        self.core = ChatCore(chat.id, sql, settings, model, hub, FakeSockets(), FakeAlarms(), clock)

    async def settle(self):
        while self.core.running:
            await asyncio.sleep(0)
            await self.core._driver


async def a_chat_with_a_card(chat, sql, clock, hub):
    c = Core(chat, sql, clock, ScriptedModel(("", [tool_call(MAKE, {})]), "Check the card."), hub)
    await c.core.submit(kinds.USER, "pay")
    await c.settle()
    return c


@pytest.fixture
def guest(chat):
    return Access.objects.create(chat=chat, visitor=f"v:{OTHER}")


class TestTheOwnerOfAChatsCalls:
    async def test_the_models_calls_carry_the_key_of_the_chats_owner(self, chat, sql, clock):
        hub = FakeHub({MAKE: quote_result()})
        await a_chat_with_a_card(chat, sql, clock, hub)
        assert hub.owners == [ledger_owner("v:a")]

    async def test_a_cards_calls_and_a_webhooks_refresh_carry_it_too_whatever_the_card_asks(
        self, chat, sql, clock
    ):
        hub = CardHub(
            {MAKE: quote_result("awaiting_approval")},
            {"approve_quote": ordered("qt-1"), "verify_quote": ordered("qt-1")},
        )
        hub.views = {MAKE: "ui://s/card.html"}
        c = Core(chat, sql, clock, ScriptedModel(("", [tool_call(MAKE, {})]), "ok"), hub)
        await c.core.submit(kinds.USER, "pay")
        await c.settle()
        hub.owners.clear()
        await c.core.card_call(
            "s", "approve_quote", {"quote_id": "qt-1", "owner": OTHER, "_meta": {"owner": OTHER}}
        )
        assert await c.core.refresh_card("qt-1") is True
        assert hub.owners == [ledger_owner("v:a")] * 2

    async def test_a_chat_of_another_owner_has_another_key(self, chat, other_chat, sql, clock):
        first, second = FakeHub({MAKE: quote_result()}), FakeHub({MAKE: quote_result()})
        await a_chat_with_a_card(chat, sql, clock, first)
        await a_chat_with_a_card(other_chat, sql, clock, second)
        assert first.owners != second.owners and second.owners == [ledger_owner("v:b")]

    async def test_a_guest_let_in_by_a_share_link_spends_the_chat_owners_allowance_not_their_own(
        self, chat, guest, sql, clock
    ):
        hub = CardHub({MAKE: quote_result()}, {"approve_quote": ordered("qt-1")})
        hub.views = {MAKE: "ui://s/card.html"}
        c = Core(chat, sql, clock, ScriptedModel(("", [tool_call(MAKE, {})]), "ok"), hub)
        await c.core.submit(kinds.USER, "pay")
        await c.settle()
        await c.core.card_call("s", "approve_quote", {"quote_id": "qt-1"})
        assert set(hub.owners) == {ledger_owner("v:a")} and ledger_owner(f"v:{OTHER}") not in hub.owners


@pytest.mark.django_db
class TestWhatABrowserSends:
    def test_a_header_or_a_body_naming_an_owner_reaches_the_relay_as_nothing(self, visitor, backend):
        chat_id = visitor.new_chat()
        backend.card_answer = {"result": {"content": []}}
        visitor.client.post(
            f"/c/{chat_id}/call",
            json.dumps(
                {
                    "server": "s",
                    "name": "approve_quote",
                    "arguments": {"quote_id": "q"},
                    "_meta": {"owner": OTHER},
                    "owner": OTHER,
                }
            ),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=visitor.token(),
            **{"HTTP_X_LEDGER_OWNER": OTHER},
        )
        assert backend.submitted[-1] == (chat_id, "card_call", "s", "approve_quote", {"quote_id": "q"})

    def test_a_chat_of_another_visitor_is_not_reachable_to_relay_a_card_call(
        self, visitor, backend, other_chat
    ):
        backend.card_answer = {"result": {"content": []}}
        refused = visitor.post(
            f"/c/{other_chat.id}/call", json={"server": "s", "name": "approve_quote", "arguments": {}}
        )
        assert refused.status_code == 404 and backend.submitted == []
