# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wallet is an account's alone on the host's side: only an account's turn is shown the wallet tool and
may call it, only an account's card reaches the wallet connector, every connector is told a call is an
account's (so the approval card can offer the wallet), and a guest of a shared chat cannot use the owner's
wallet."""

import asyncio
import json

import httpx
import pytest

from accounts.owner import account_owner
from chat.models import Access, Chat
from turns import kinds, wallet
from turns.chat_core import ChatCore
from turns.hub import MEMORY_OWNER_HEADER, OWNER_HEADER, Hub, HubError
from turns.permissions import Permissions
from turns.settings import Settings

from .account_support import ACCOUNT_KEY, Device
from .card_support import APPROVAL, CardHub, listed
from .memory_support import ACCOUNT, AGENT, VISITOR
from .support import FakeAlarms, FakeSockets, ScriptedModel

BALANCE = "wallet__wallet_balance"
CARD = "ui://wallet/card.html"
CARD_ID = "c0" * 16
OWNER_KEY = "ab" * 16
NO_NOTES = {"content": [], "structuredContent": {"index": ""}}


def tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {}}}


TOOLS = [tool("airtime__create_airtime_quote"), tool(BALANCE)]


def names(tools: list[dict]) -> list[str]:
    return [t["function"]["name"] for t in tools]


class TestWhatATurnIsShown:
    def test_an_account_is_shown_the_wallet_tool(self):
        assert BALANCE in names(Permissions(ACCOUNT).tools(TOOLS))

    @pytest.mark.parametrize("owner", [VISITOR, AGENT, "p:agent-own"])
    def test_anyone_else_is_never_shown_it(self, owner):
        assert names(Permissions(owner).tools(TOOLS)) == ["airtime__create_airtime_quote"]

    def test_a_personal_agents_turn_without_the_account_is_not_shown_it_either(self):
        assert BALANCE not in names(Permissions(VISITOR, scopes=frozenset({"payments"})).tools(TOOLS))

    @pytest.mark.parametrize("owner", [VISITOR, AGENT])
    def test_a_call_to_it_without_an_account_is_refused_before_it_leaves_the_host(self, owner):
        refusal = Permissions(owner).refusal(BALANCE)
        assert refusal is not None and refusal.outcome.text == wallet.NOT_AN_ACCOUNT

    def test_an_accounts_call_may_go(self):
        assert Permissions(ACCOUNT).refusal(BALANCE) is None


SEEN: list[httpx.Request] = []


def answer(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    body = json.loads(request.content)
    listing = [
        {
            "name": "wallet_balance",
            "inputSchema": {"type": "object"},
            "_meta": {"ui": {"visibility": ["model"]}},
        },
        {
            "name": "approve_quote",
            "inputSchema": {"type": "object"},
            "_meta": {"ui": {"visibility": ["app"]}},
        },
    ]
    result = {"tools/list": {"tools": listing}, "tools/call": {"content": []}}.get(body.get("method"), {})
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": body.get("id"), "result": result})


@pytest.fixture
def hub():
    SEEN.clear()
    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    return Hub({"wallet": "http://w/mcp", "airtime": "http://a/mcp"}, client)


def calls() -> list[httpx.Request]:
    return [r for r in SEEN if json.loads(r.content).get("method") == "tools/call"]


class TestWhatAConnectorIsTold:
    async def test_an_accounts_calls_name_the_account_to_every_connector(self, hub):
        await hub.call_model_tool(BALANCE, {}, OWNER_KEY, "k" * 40, account=True)
        await hub.call_app_tool("airtime", "approve_quote", {"quote_id": "qt-1"}, OWNER_KEY, account=True)
        sent = calls()
        assert [(r.headers[OWNER_HEADER], r.headers[MEMORY_OWNER_HEADER]) for r in sent] == [
            (OWNER_KEY,) * 2
        ] * 2

    async def test_a_visitors_calls_name_no_account(self, hub):
        await hub.call_model_tool(BALANCE, {}, OWNER_KEY, "k" * 40)
        await hub.call_app_tool("airtime", "approve_quote", {"quote_id": "qt-1"}, OWNER_KEY)
        assert all(MEMORY_OWNER_HEADER not in r.headers for r in calls())


WALLET_LISTING = [listed("wallet_balance", CARD, "model"), listed("start_topup", CARD, "app")]
APPROVAL_LISTING = [listed("approve_quote", APPROVAL, "app")]


class WalletCardHub(CardHub):
    async def tools(self, server: str):
        return WALLET_LISTING if server == "wallet" else APPROVAL_LISTING


def wallet_card() -> dict:
    data = {"card_id": CARD_ID, "wallet": {"balanceKobo": 0, "balance": "₦0", "entries": []}}
    return {"content": [{"type": "text", "text": "The wallet holds ₦0."}], "structuredContent": data}


@pytest.fixture
def account_chat(db):
    return Chat.objects.create(owner=ACCOUNT)


@pytest.fixture
def visitor_chat(db):
    return Chat.objects.create(owner=VISITOR)


async def core_for(chat, sql, clock):
    hub = WalletCardHub(
        {BALANCE: wallet_card(), "airtime__create_airtime_quote": wallet_card()},
        {"start_topup": wallet_card(), "approve_quote": wallet_card(), "memory_index": NO_NOTES},
    )
    settings = Settings(mcp_url="x", llm_base_url="m", llm_api_key="k")
    core = ChatCore(chat.id, sql, settings, ScriptedModel("ok"), hub, FakeSockets(), FakeAlarms(), clock)
    for server, uri, ref in (("wallet", CARD, CARD_ID), ("s", APPROVAL, "qt-1")):
        payload = {"server": server, "tool": "made", "resource_uri": uri, "result": wallet_card()}
        await core.log.append(kinds.CARD, payload, ref=ref)
    return core, hub


async def offered_in_a_turn(core) -> list[str]:
    await core.submit(kinds.USER, "what is in my wallet")
    while core.running:
        await asyncio.sleep(0)
        await core._driver
    return core._model.offered[0]


class TestATurn:
    async def test_an_accounts_model_is_offered_the_wallet_tool(self, account_chat, sql, clock):
        core, _ = await core_for(account_chat, sql, clock)
        assert BALANCE in await offered_in_a_turn(core)

    async def test_a_visitors_model_is_never_offered_it(self, visitor_chat, sql, clock):
        core, _ = await core_for(visitor_chat, sql, clock)
        assert await offered_in_a_turn(core) == ["airtime__create_airtime_quote"]


class TestACardsCalls:
    async def test_a_wallet_card_of_an_accounts_chat_is_relayed_as_the_accounts(
        self, account_chat, sql, clock
    ):
        core, hub = await core_for(account_chat, sql, clock)
        await core.card_call("wallet", "start_topup", {"card_id": CARD_ID, "amount_naira": 500})
        assert hub.app_calls == [("wallet", "start_topup", {"card_id": CARD_ID, "amount_naira": 500})]
        assert hub.accounts == [True]

    async def test_a_wallet_card_of_anyone_elses_chat_reaches_nothing(self, visitor_chat, sql, clock):
        core, hub = await core_for(visitor_chat, sql, clock)
        with pytest.raises(HubError, match=wallet.NOT_AN_ACCOUNT):
            await core.card_call("wallet", "start_topup", {"card_id": CARD_ID, "amount_naira": 500})
        assert hub.app_calls == []

    async def test_an_accounts_approval_card_tells_the_connector_it_is_an_accounts(
        self, account_chat, sql, clock
    ):
        core, hub = await core_for(account_chat, sql, clock)
        await core.card_call("s", "approve_quote", {"quote_id": "qt-1", "funding": "wallet"})
        assert hub.accounts == [True]

    async def test_a_visitors_approval_card_tells_the_connector_nothing(self, visitor_chat, sql, clock):
        core, hub = await core_for(visitor_chat, sql, clock)
        await core.card_call("s", "approve_quote", {"quote_id": "qt-1", "funding": "wallet"})
        assert hub.accounts == [False]


@pytest.fixture
def ada(sign_in_on, key, backend):
    device = Device()
    assert device.sign_in(key).status_code == 200
    backend.owner = account_owner("uid-abc", ACCOUNT_KEY)
    return device


@pytest.mark.django_db
def test_a_guest_of_a_shared_chat_cannot_use_the_owners_wallet(ada, sign_in_on, backend):
    chat = ada.chat()
    guest = Device()
    Access.objects.create(chat=Chat.objects.get(pk=chat), visitor=guest.client.get("/").wsgi_request.owner)
    approve = {"quote_id": "qt-1", "approval_token": "t", "displayed_amount_kobo": 50_000}
    for body in (
        {"server": "wallet", "name": "start_topup", "arguments": {"card_id": CARD_ID, "amount_naira": 500}},
        {"server": "wallet", "name": "wallet_view", "arguments": {"card_id": CARD_ID}},
        {"server": "airtime", "name": "approve_quote", "arguments": {**approve, "funding": "wallet"}},
    ):
        refused = guest.post(f"/c/{chat}/call", body)
        assert refused.status_code == 403 and "Only the owner of this chat" in refused.json()["error"]
    assert [c for c in backend.submitted if c[1] == "card_call"] == []
    paid_by_checkout = {"server": "airtime", "name": "approve_quote", "arguments": approve}
    assert guest.post(f"/c/{chat}/call", paid_by_checkout).status_code == 200
    assert (
        ada.post(
            f"/c/{chat}/call", {**paid_by_checkout, "arguments": {**approve, "funding": "wallet"}}
        ).status_code
        == 200
    )
