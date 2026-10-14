# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where Paystack Index sends the browser after a person signs in there: only the signed-in account whose
browser arrives is acted for, the code and the state go to the merchants connector as that account and nowhere
else, a refusal is shown in the connector's words and escaped, and a guest of a shared chat cannot press the
connect card or approve a payment from the owner's Index account."""

import asyncio

import pytest

from accounts.owner import account_owner
from chat.models import Access, Chat
from turns import kinds
from turns.chat_core import ChatCore
from turns.settings import Settings

from .account_support import ACCOUNT_KEY, Device
from .card_support import CardHub, listed
from .support import FakeAlarms, FakeSockets, ScriptedModel, tool_call

URL = "/connect/index/callback"
CARD_ID = "cn-" + "0" * 20
pytestmark = pytest.mark.django_db


@pytest.fixture
def ada(sign_in_on, key, backend):
    device = Device()
    assert device.sign_in(key).status_code == 200
    backend.owner = account_owner("uid-abc", ACCOUNT_KEY)
    return device


class TestTheCallback:
    def test_hands_the_code_and_state_to_the_connector_as_the_signed_in_account(self, ada, backend):
        answered = ada.client.get(URL, {"code": "the-code", "state": "the-state"})
        assert answered.status_code == 200 and b"Connected" in answered.content
        assert backend.account_calls == [
            (
                account_owner("uid-abc", ACCOUNT_KEY),
                "complete_connection",
                {"code": "the-code", "state": "the-state"},
            )
        ]

    def test_says_nothing_about_the_code_or_state_and_is_not_kept_or_referred(self, ada):
        answered = ada.client.get(URL, {"code": "secret-code-value", "state": "secret-state-value"})
        assert b"secret-code-value" not in answered.content and b"secret-state-value" not in answered.content
        assert answered["Cache-Control"] == "no-store" and answered["Referrer-Policy"] == "no-referrer"

    def test_a_browser_that_is_not_signed_in_is_acted_for_by_nobody(self, backend, sign_in_on):
        answered = Device().client.get(URL, {"code": "c", "state": "s"})
        assert answered.status_code == 401 and b"Sign in to 234" in answered.content
        assert backend.account_calls == []

    def test_a_sign_in_the_person_refused_ends_the_attempt(self, ada, backend):
        answered = ada.client.get(URL, {"error": "access_denied", "state": "the-state"})
        assert answered.status_code == 200 and b"Nothing was connected" in answered.content
        assert [(name, args) for _, name, args in backend.account_calls] == [
            ("connection_declined", {"state": "the-state"})
        ]

    def test_a_refusal_is_shown_in_the_connectors_words_without_its_code(self, ada, backend):
        backend.account_answer = {
            "isError": True,
            "content": [{"type": "text", "text": "INDEX_STATE: This sign-in is not one 234 is waiting for."}],
        }
        answered = ada.client.get(URL, {"code": "c", "state": "s"})
        assert answered.status_code == 400
        assert b"This sign-in is not one 234 is waiting for." in answered.content
        assert b"INDEX_STATE" not in answered.content and b"Could not connect" in answered.content

    def test_what_the_connector_says_is_escaped(self, ada, backend):
        backend.account_answer = {
            "isError": True,
            "content": [{"type": "text", "text": "X: <script>alert(1)</script>"}],
        }
        answered = ada.client.get(URL, {"code": "c", "state": "s"})
        assert b"<script>alert" not in answered.content and b"&lt;script&gt;" in answered.content

    @pytest.mark.parametrize(
        "query",
        [
            {},
            {"code": "c"},
            {"state": "s"},
            {"code": "c" * 2001, "state": "s"},
            {"code": "c", "state": "s" * 2001},
        ],
    )
    def test_a_callback_without_what_it_needs_reaches_no_connector(self, ada, backend, query):
        assert ada.client.get(URL, query).status_code == 400
        assert backend.account_calls == []

    def test_is_rate_limited_per_account(self, ada, backend):
        backend.allow = False
        assert ada.client.get(URL, {"code": "c", "state": "s"}).status_code == 429
        assert backend.account_calls == [] and backend.rate_keys[-1].startswith("connect-index:")

    def test_only_get_is_taken(self, ada, backend):
        assert ada.post(URL, {"code": "c", "state": "s"}).status_code == 405
        assert backend.account_calls == []


class TestGuestsOfASharedChat:
    def guest_of(self, ada):
        chat = ada.chat()
        guest = Device()
        Access.objects.create(
            chat=Chat.objects.get(pk=chat), visitor=guest.client.get("/").wsgi_request.owner
        )
        return chat, guest

    @pytest.mark.parametrize(
        ("name", "arguments"),
        [
            ("connection_status", {"card_id": CARD_ID}),
            ("restart_connection", {"card_id": CARD_ID}),
            ("send_link_code", {"card_id": CARD_ID, "phone": "08031234567"}),
            ("confirm_link_code", {"card_id": CARD_ID, "phone": "08031234567", "code": "123456"}),
            ("disconnect_account", {"card_id": CARD_ID}),
            (
                "approve_quote",
                {
                    "quote_id": "qt-1",
                    "approval_token": "t",
                    "displayed_amount_kobo": 5,
                    "funding": "external",
                },
            ),
        ],
    )
    def test_cannot_connect_disconnect_or_pay_from_the_owners_index_account(
        self, ada, backend, name, arguments
    ):
        chat, guest = self.guest_of(ada)
        refused = guest.post(f"/c/{chat}/call", {"server": "merchants", "name": name, "arguments": arguments})
        assert refused.status_code == 403 and "Only the owner of this chat" in refused.json()["error"]
        assert [c for c in backend.submitted if c[1] == "card_call"] == []

    def test_the_owner_can_and_a_guest_still_approves_at_the_checkout_as_before(self, ada, backend):
        chat, guest = self.guest_of(ada)
        approve = {"quote_id": "qt-1", "approval_token": "t", "displayed_amount_kobo": 5}
        owners = {
            "server": "merchants",
            "name": "approve_quote",
            "arguments": {**approve, "funding": "external"},
        }
        assert ada.post(f"/c/{chat}/call", owners).status_code == 200
        checkout = {"server": "merchants", "name": "approve_quote", "arguments": approve}
        assert guest.post(f"/c/{chat}/call", checkout).status_code == 200


CONNECT_VIEW = "ui://s/connect.html"
CONNECT = "s__connect_account"


def connection(state: str) -> dict:
    return {
        "content": [{"type": "text", "text": "The connect card is shown."}],
        "structuredContent": {
            "card_id": CARD_ID,
            "connection": {"provider": "Paystack Index", "state": state},
        },
    }


class ConnectHub(CardHub):
    """A connector whose model tool opens the connect card and whose card tool says how the sign-in stands."""

    def __init__(self):
        super().__init__(
            {CONNECT: connection("authorize")},
            {"connection_status": connection("connected")},
            {CONNECT: CONNECT_VIEW},
        )

    async def tools(self, server):
        return [
            listed("connect_account", CONNECT_VIEW, "model"),
            listed("connection_status", CONNECT_VIEW, "app"),
        ]


async def test_a_connect_card_is_recorded_and_its_changed_state_is_pushed_to_every_tab(chat, sql, clock):
    model = ScriptedModel(("", [tool_call(CONNECT, {})]), "Connect on the card.")
    settings = Settings(mcp_url="x", llm_base_url="m", llm_api_key="k")
    core = ChatCore(chat.id, sql, settings, model, ConnectHub(), FakeSockets(), FakeAlarms(), clock)
    await core.submit(kinds.USER, "connect my index")
    while core.running:
        await asyncio.sleep(0)
        await core._driver
    [card] = [e for e in await core.log.read() if e.type == kinds.CARD]
    assert card.ref == CARD_ID and card.payload["resource_uri"] == CONNECT_VIEW
    await core.card_call("s", "connection_status", {"card_id": CARD_ID})
    [state] = [e for e in await core.log.read() if e.type == kinds.CARD_STATE]
    assert state.ref == CARD_ID
    assert state.payload["result"]["structuredContent"]["connection"]["state"] == "connected"
