# SPDX-License-Identifier: AGPL-3.0-or-later
"""Settings to running connectors: which connector talks to which provider, over which transport.
Test and sandbox mode run here on a scripted transport: no real Paystack or VTpass call is made."""

import pytest

from checkout.app import build_app
from checkout.audit import Audit
from checkout.config import Settings
from checkout.errors import ConfigError
from checkout.sqlite_db import SqliteDb
from tests.keys import fake_key
from tests.support import FakeClock, ScriptedTransport, json_reply

TEST_KEY = fake_key("test")
VTPASS = {"VTPASS_API_KEY": "api", "VTPASS_PUBLIC_KEY": "PK_public", "VTPASS_SECRET_KEY": "SK_secret"}


def app_with(transport, **env):
    settings = Settings.from_env({"APPROVAL_SECRET": "x-not-real", **env}.get)
    lines: list[str] = []
    clock = FakeClock()
    return build_app(settings, SqliteDb(), clock, Audit([lines.append], clock), transport), lines


def paystack_ok(sent):
    if sent.url.endswith("/transaction/initialize"):
        return json_reply(
            {
                "status": True,
                "data": {
                    "authorization_url": "https://checkout.paystack.com/abc",
                    "access_code": "abc",
                    "reference": sent.body["reference"],
                },
            }
        )
    return json_reply({"status": False, "message": "not scripted"}, 404)


async def test_test_mode_sends_the_real_clients_calls_to_paystack_with_the_test_key():
    transport = ScriptedTransport(paystack_ok)
    app, _ = app_with(transport, PAYSTACK_TEST_SECRET_KEY=TEST_KEY)
    result = await _pay_and_approve(app)
    assert result["phase"] == "awaiting_checkout"
    assert result["checkoutUrl"] == "https://checkout.paystack.com/abc"
    call = transport.calls[0]
    assert call.url == "https://api.paystack.co/transaction/initialize"
    assert call.headers["authorization"] == f"Bearer {TEST_KEY}"
    assert result["mode"]["label"] == "Paystack test mode: no real money moves"


async def _pay_and_approve(app):
    from checkout.flows.payment import PaymentFlow

    flow = PaymentFlow(app.contexts["paystack-pay"])
    issued = await flow.create_quote(
        amount_kobo=250_000, amount_as_user_said="2500", description="Lunch", merchant="Demo",
        merchant_ref=None, idempotency_key="wiring-key-0001",
    )  # fmt: skip
    return await flow.approve(issued.quote["id"], issued.approval_token, 250_000)


async def test_simulated_mode_makes_no_outside_call_at_all():
    transport = ScriptedTransport(lambda _: pytest.fail("a simulated connector reached the network"))
    app, _ = app_with(transport)
    assert (await _pay_and_approve(app))["checkoutUrl"].startswith("http://localhost:8787/sim/checkout/")
    assert transport.calls == []


async def test_one_connector_can_simulate_while_the_rest_use_the_real_test_account():
    transport = ScriptedTransport(paystack_ok)
    app, _ = app_with(transport, PAYSTACK_TEST_SECRET_KEY=TEST_KEY, SEND_MONEY_MODE="simulated")
    assert {c: ctx.modes.paystack for c, ctx in app.contexts.items()} == {
        "paystack-pay": "test",
        "send-money": "simulated",
        "airtime": "test",
        "food-order": "test",
    }
    from checkout.flows.transfer import TransferFlow

    issued = await TransferFlow(app.contexts["send-money"]).create_quote(
        account_number="0000000000", bank_code="057", amount_kobo=100_000, amount_as_user_said="1k",
        narration=None, idempotency_key="wiring-key-0002",
    )  # fmt: skip
    assert transport.calls == [], "the simulated transfer connector did not reach Paystack"
    assert (
        issued.quote["mode"]["label"]
        == "Simulated: no money moves (this Paystack account cannot make payouts)"
    )


async def test_the_owners_starter_business_setup_says_why_transfers_are_simulated():
    app, _ = app_with(
        ScriptedTransport(paystack_ok), PAYSTACK_TEST_SECRET_KEY=TEST_KEY, SEND_MONEY_MODE="simulated"
    )
    assert app.contexts["send-money"].modes.reason == "this Paystack account cannot make payouts"
    assert app.contexts["paystack-pay"].modes.reason is None


async def test_sandbox_mode_talks_to_the_vtpass_sandbox_with_the_owners_keys():
    def answer(sent):
        assert sent.url.startswith("https://sandbox.vtpass.com/api/")
        return json_reply({"code": 1, "contents": {"balance": 100000}})

    transport = ScriptedTransport(answer)
    app, _ = app_with(transport, **VTPASS)
    assert app.contexts["airtime"].modes.vtpass == "sandbox"
    access = await app.contexts["airtime"].vtpass.check_access()
    assert access.ok
    assert (
        transport.calls[0].headers["api-key"] == "api"
        and transport.calls[0].headers["public-key"] == "PK_public"
    )


async def test_vtpass_debug_lines_go_to_the_audit_log_redacted():
    app, lines = app_with(
        ScriptedTransport(lambda _: json_reply("Invalid Credentials.", 401)), VTPASS_DEBUG="1", **VTPASS
    )
    await app.contexts["airtime"].vtpass.check_access()
    logged = "\n".join(lines)
    assert "vtpass reply: HTTP 401" in logged and "SK_secret" not in logged


async def test_only_the_airtime_connector_has_a_vtpass_client():
    app, _ = app_with(ScriptedTransport(lambda _: None))
    assert {c: ctx.vtpass is not None for c, ctx in app.contexts.items()} == {
        "paystack-pay": False, "send-money": False, "airtime": True, "food-order": False,
    }  # fmt: skip


def test_a_live_key_stops_the_server_from_starting_in_any_mode():
    for mode in ("simulated", "test"):
        with pytest.raises(ConfigError, match="live key"):
            app_with(None, PAYSTACK_TEST_SECRET_KEY=fake_key("live"), PAYSTACK_MODE=mode)


def test_the_startup_line_names_each_connectors_modes_and_limits_and_no_key():
    _, lines = app_with(ScriptedTransport(lambda _: None), PAYSTACK_TEST_SECRET_KEY=TEST_KEY, **VTPASS)
    startup = [line for line in lines if '"startup"' in line]
    assert len(startup) == 4
    assert '"connector": "airtime"' in "\n".join(startup) and '"vtpass_mode": "sandbox"' in "\n".join(startup)
    assert "abcdefgh12345678" not in "\n".join(lines) and "SK_secret" not in "\n".join(lines)
