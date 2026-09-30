# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paystack's popup as an option of the approval card: the connector hands the card the transaction's access
code in `_meta` while the person is at the checkout, only in Paystack test mode, never to the model or in
anything that is kept, and asks the host for the two origins the popup needs, only when it can use them."""

import json

import pytest

from checkout.app import build_app
from checkout.audit import Audit
from checkout.config import Settings
from checkout.errors import ConfigError
from checkout.paystack.inline import INLINE_CHECKOUT_CSP
from checkout.sqlite_db import SqliteDb
from tests.connector_support import approve_args, key
from tests.keys import fake_key
from tests.support import FakeClock, ScriptedTransport, Stack, json_reply, make_stack

ACCESS_CODE = "ac_inline_0123456789"
TEST_KEY = fake_key("test")


def paystack(sent):
    if sent.url.endswith("/transaction/initialize"):
        data = {
            "authorization_url": "https://checkout.paystack.com/" + ACCESS_CODE,
            "access_code": ACCESS_CODE,
            "reference": sent.body["reference"],
        }
        return json_reply({"status": True, "data": data})
    if "/transaction/verify/" in sent.url:
        data = {
            "status": "abandoned",
            "reference": sent.url.rsplit("/", 1)[1],
            "amount": 250_000,
            "currency": "NGN",
        }
        return json_reply({"status": True, "data": data})
    return json_reply({"status": False, "message": "not scripted"}, 404)


def stack_with(**env) -> tuple[Stack, ScriptedTransport]:
    transport = ScriptedTransport(paystack)
    settings = Settings.from_env({"APPROVAL_SECRET": "x-not-real", "PAYSTACK_PAY_MODE": "test", **env}.get)
    clock, lines = FakeClock(), []
    db = SqliteDb()
    app = build_app(settings, db, clock, Audit([lines.append], clock), transport)
    return Stack(app, clock, db, lines), transport


async def quote(stack: Stack):
    return await stack.call(
        "paystack-pay", "create_payment_quote",
        amount_kobo=250_000, amount_as_user_said="2500", description="Lunch", merchant="Demo",
        idempotency_key=key("inline"),
    )  # fmt: skip


def quote_id_of(result) -> str:
    return result["structuredContent"]["quote"]["id"]


def code_in(result) -> str | None:
    return ((result.get("_meta") or {}).get("paystack") or {}).get("accessCode")


async def resource_meta(stack: Stack, uri="ui://paystack-pay/card.html"):
    listed = (await stack.mcp("paystack-pay", "resources/list"))["result"]["resources"]
    read = (await stack.mcp("paystack-pay", "resources/read", {"uri": uri}))["result"]["contents"][0]
    return next(r for r in listed if r["uri"] == uri)["_meta"]["ui"], read["_meta"]["ui"]


async def test_the_card_is_given_the_access_code_in_meta_when_it_approves():
    stack, _ = stack_with(PAYSTACK_TEST_SECRET_KEY=TEST_KEY)
    made = await quote(stack)
    assert code_in(made) is None
    approved = await stack.call("paystack-pay", "approve_quote", **approve_args(made))
    assert code_in(approved) == ACCESS_CODE
    assert approved["structuredContent"]["quote"]["phase"] == "awaiting_checkout"
    assert (
        approved["structuredContent"]["quote"]["checkoutUrl"]
        == "https://checkout.paystack.com/" + ACCESS_CODE
    )


async def test_the_access_code_is_nowhere_else_in_the_result():
    stack, _ = stack_with(PAYSTACK_TEST_SECRET_KEY=TEST_KEY)
    made = await quote(stack)
    approved = await stack.call("paystack-pay", "approve_quote", **approve_args(made))
    outside_meta = json.dumps({k: v for k, v in approved.items() if k != "_meta"})
    assert ACCESS_CODE not in outside_meta.replace("https://checkout.paystack.com/" + ACCESS_CODE, "")
    status = await stack.call(
        "paystack-pay", "get_quote_status", quote_id=approved["structuredContent"]["quote"]["id"]
    )
    assert ACCESS_CODE not in json.dumps(status) and "_meta" not in status
    assert not any(ACCESS_CODE in line for line in stack.audit_lines)


async def test_a_card_that_reloads_is_given_it_again_by_verify_while_the_person_is_at_the_checkout():
    stack, _ = stack_with(PAYSTACK_TEST_SECRET_KEY=TEST_KEY)
    made = await quote(stack)
    await stack.call("paystack-pay", "approve_quote", **approve_args(made))
    checked = await stack.call(
        "paystack-pay", "verify_quote", quote_id=made["structuredContent"]["quote"]["id"]
    )
    assert (
        code_in(checked) == ACCESS_CODE
        and checked["structuredContent"]["quote"]["phase"] == "awaiting_checkout"
    )


async def test_once_the_checkout_is_closed_the_code_is_no_longer_handed_out():
    stack, _ = stack_with(PAYSTACK_TEST_SECRET_KEY=TEST_KEY)
    made = await quote(stack)
    await stack.call("paystack-pay", "approve_quote", **approve_args(made))
    closed = await stack.call(
        "paystack-pay",
        "verify_quote",
        quote_id=made["structuredContent"]["quote"]["id"],
        checkout_closed=True,
    )
    assert closed["structuredContent"]["quote"]["phase"] == "abandoned" and code_in(closed) is None


async def test_the_simulator_has_no_popup_and_its_code_is_not_handed_out():
    simulated = make_stack()
    made = await quote(simulated)
    approved = await simulated.call("paystack-pay", "approve_quote", **approve_args(made))
    assert (
        approved["structuredContent"]["quote"]["phase"] == "awaiting_checkout" and code_in(approved) is None
    )
    assert not (await resource_meta(simulated))[1].get("csp")
    assert "accessCode" not in (await simulated.ledger.get(quote_id_of(made))).progress


async def test_a_code_that_somehow_sits_in_a_simulated_quote_is_still_not_handed_out():
    simulated = make_stack()
    made = await quote(simulated)
    approved = await simulated.call("paystack-pay", "approve_quote", **approve_args(made))
    await simulated.ledger.patch_progress(quote_id_of(approved), {"accessCode": "planted"})
    checked = await simulated.call("paystack-pay", "verify_quote", quote_id=quote_id_of(approved))
    assert code_in(checked) is None


async def test_the_approval_card_asks_the_host_for_paystacks_two_origins_in_test_mode_only():
    stack, _ = stack_with(PAYSTACK_TEST_SECRET_KEY=TEST_KEY)
    listed, read = await resource_meta(stack)
    assert listed == read == {"prefersBorder": False, "csp": INLINE_CHECKOUT_CSP}
    assert INLINE_CHECKOUT_CSP == {
        "resourceDomains": ["https://js.paystack.co"],
        "frameDomains": ["https://checkout.paystack.com"],
    }


async def test_the_switch_turns_the_popup_off_everywhere():
    stack, _ = stack_with(PAYSTACK_TEST_SECRET_KEY=TEST_KEY, INLINE_PAYSTACK="0")
    assert (await resource_meta(stack))[1] == {"prefersBorder": False}
    made = await quote(stack)
    approved = await stack.call("paystack-pay", "approve_quote", **approve_args(made))
    assert (
        code_in(approved) is None and approved["structuredContent"]["quote"]["phase"] == "awaiting_checkout"
    )


async def test_other_cards_of_the_connector_declare_nothing():
    stack, _ = stack_with(PAYSTACK_TEST_SECRET_KEY=TEST_KEY)
    listed = (await stack.mcp("food-order", "resources/list"))["result"]["resources"]
    menu = next(r for r in listed if r["uri"].endswith("menu.html"))
    assert "csp" not in menu["_meta"]["ui"]


def settings_with(**env):
    return Settings.from_env({"APPROVAL_SECRET": "x-not-real", **env}.get)


def test_paystack_is_reached_at_its_own_address_unless_a_test_rig_on_this_machine_stands_in():
    assert settings_with().paystack.api_url == "https://api.paystack.co"
    assert (
        settings_with(PAYSTACK_API_URL="https://api.paystack.co").paystack.api_url
        == "https://api.paystack.co"
    )
    assert (
        settings_with(PAYSTACK_API_URL="http://127.0.0.1:8926/").paystack.api_url == "http://127.0.0.1:8926"
    )
    assert settings_with(PAYSTACK_API_URL="http://localhost:8926").paystack.api_url == "http://localhost:8926"


@pytest.mark.parametrize(
    "address",
    [
        "http://api.paystack.co",
        "https://evil.example",
        "https://127.0.0.1:8926",
        "http://127.0.0.1",
        "http://127.0.0.1:99999",
        "http://127.0.0.1:8926/transaction",
        "http://127.0.0.1:8926?x=1",
        "http://user@127.0.0.1:8926",
        "ftp://127.0.0.1:8926",
        "http://10.0.0.5:8926",
    ],
)
def test_no_other_address_may_receive_the_key(address):
    with pytest.raises(ConfigError, match="PAYSTACK_API_URL"):
        settings_with(PAYSTACK_API_URL=address, PAYSTACK_TEST_SECRET_KEY=TEST_KEY)


async def test_a_test_rig_address_is_where_the_client_sends_its_calls():
    transport = ScriptedTransport(paystack)
    settings = settings_with(
        PAYSTACK_PAY_MODE="test", PAYSTACK_TEST_SECRET_KEY=TEST_KEY, PAYSTACK_API_URL="http://127.0.0.1:8926"
    )
    clock = FakeClock()
    stack = Stack(build_app(settings, SqliteDb(), clock, Audit([], clock), transport), clock, SqliteDb())
    made = await quote(stack)
    await stack.call("paystack-pay", "approve_quote", **approve_args(made))
    assert transport.calls[0].url == "http://127.0.0.1:8926/transaction/initialize"


def test_a_live_key_is_still_refused_whatever_else_is_set():
    with pytest.raises(ConfigError, match="live key"):
        settings_with(
            PAYSTACK_PAY_MODE="test", PAYSTACK_TEST_SECRET_KEY=fake_key("live"), INLINE_PAYSTACK="1"
        )


async def test_a_test_rig_can_make_the_approval_card_ask_for_more_than_it_needs():
    extra = json.dumps(
        {"connectDomains": ["https://api.evil.example.com"], "resourceDomains": ["data:", "*"]}
    )
    stack, _ = stack_with(PAYSTACK_TEST_SECRET_KEY=TEST_KEY, CARD_CSP_EXTRA=extra, ENABLE_TEST_ROUTES="1")
    csp = (await resource_meta(stack))[1]["csp"]
    assert csp["connectDomains"] == ["https://api.evil.example.com"]
    assert csp["resourceDomains"] == ["https://js.paystack.co", "data:", "*"]
    assert csp["frameDomains"] == ["https://checkout.paystack.com"]


def test_the_extra_origins_are_a_test_setting_and_must_be_json():
    with pytest.raises(ConfigError, match="test setting"):
        settings_with(CARD_CSP_EXTRA='{"connectDomains": []}')
    with pytest.raises(ConfigError, match="JSON"):
        settings_with(CARD_CSP_EXTRA="not json", ENABLE_TEST_ROUTES="1")
