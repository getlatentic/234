# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which number VTpass is sent, in each mode, and that only the sandbox is ever sent a substitute."""

import json

import pytest

from checkout.flows.airtime import AirtimeFlow
from checkout.vtpass.recipient import TRIGGER_NUMBERS, number_for_vtpass
from tests.support import ScriptedTransport, json_reply
from tests.test_app_wiring import VTPASS, app_with

TYPED = "07031234567"
SUCCESS = "08011111111"
TRIGGERS = ["08011111111", "201000000000", "500000000000", "400000000000", "300000000000", "100000000000"]


def test_the_sandbox_is_sent_its_success_number_for_a_real_typed_number():
    assert number_for_vtpass("sandbox", TYPED) == SUCCESS


@pytest.mark.parametrize("trigger", TRIGGERS)
def test_the_sandbox_is_sent_a_trigger_number_as_typed(trigger):
    assert number_for_vtpass("sandbox", trigger) == trigger


@pytest.mark.parametrize("mode", ["simulated", "live"])
@pytest.mark.parametrize("typed", [TYPED, *TRIGGERS])
def test_the_simulator_and_live_are_sent_the_number_as_typed(mode, typed):
    assert number_for_vtpass(mode, typed) == typed


def test_the_trigger_numbers_are_the_documented_ones_and_the_simulators_own():
    assert set(TRIGGERS) == TRIGGER_NUMBERS


def test_a_mode_nobody_defined_is_refused_rather_than_guessed():
    with pytest.raises(ValueError, match="Unknown VTpass mode"):
        number_for_vtpass("staging", TYPED)


def vtpass_answers(sent):
    if sent.url.endswith("/balance"):
        return json_reply({"code": 1, "contents": {"balance": 100000}})
    if sent.url.endswith("/pay"):
        return json_reply(
            {
                "code": "000",
                "response_description": "TRANSACTION SUCCESSFUL",
                "content": {"transactions": {"status": "delivered"}},
            }
        )
    return json_reply({}, 404)


async def paid_airtime(app, phone: str) -> dict:
    from checkout.http import handle

    flow = AirtimeFlow(app.contexts["airtime"])
    issued = await flow.create_airtime_quote(
        network="mtn", phone=phone, amount_kobo=50_000, amount_as_user_said="₦500",
        idempotency_key="recipient-key-0001",
    )  # fmt: skip
    approved = await flow.approve(issued.quote["id"], issued.approval_token, 50_000, True)
    reference = approved["checkoutUrl"].rsplit("/", 1)[1]
    await handle(app, "GET", f"/sim/checkout/{reference}", {}, b"")
    await handle(app, "POST", f"/sim/checkout/{reference}/pay", {}, b"")
    return await flow.verify(issued.quote["id"])


async def test_in_sandbox_mode_vtpass_gets_the_success_number_and_everything_else_keeps_the_typed_one():
    transport = ScriptedTransport(vtpass_answers)
    app, lines = app_with(transport, PAYSTACK_MODE="simulated", **VTPASS)
    view = await paid_airtime(app, "0703 123 4567")
    sent = [json.loads(json.dumps(c.body)) for c in transport.calls if c.url.endswith("/pay")]
    assert [c["phone"] for c in sent] == [SUCCESS]
    assert (view["phase"], view["details"]["phone"]) == ("succeeded", "0703 123 4567")
    assert view["mode"]["label"].endswith("no airtime is sent")
    assert {line["value"] for line in view["receipt"]["lines"] if line["label"] == "Number"} == {
        "0703 123 4567"
    }
    log = [json.loads(line) for line in lines]
    substituted = [e for e in log if e["event"] == "vtpass.number_substituted"]
    assert len(substituted) == 1
    assert substituted[0]["typed"] == "0703****567" and substituted[0]["sent"] == "sandbox success number"
    assert TYPED not in "\n".join(lines)


async def test_in_sandbox_mode_a_typed_trigger_number_reaches_vtpass_unchanged():
    transport = ScriptedTransport(vtpass_answers)
    app, lines = app_with(transport, PAYSTACK_MODE="simulated", **VTPASS)
    await paid_airtime(app, "201000000000")
    assert [c.body["phone"] for c in transport.calls if c.url.endswith("/pay")] == ["201000000000"]
    assert "vtpass.number_substituted" not in "\n".join(lines)


async def test_in_simulated_mode_vtpass_is_never_called_and_the_simulator_gets_the_typed_number():
    transport = ScriptedTransport(lambda _: pytest.fail("a simulated connector reached the network"))
    app, lines = app_with(transport)
    view = await paid_airtime(app, "0703 123 4567")
    assert (view["phase"], transport.calls) == ("succeeded", [])
    assert "vtpass.number_substituted" not in "\n".join(lines)
    assert (await app.db.row("SELECT phone FROM sim_vtpass"))["phone"] == TYPED
