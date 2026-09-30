# SPDX-License-Identifier: AGPL-3.0-or-later
"""The airtime and data flow, ported from the TypeScript demo's airtime-flow.test.ts."""

from dataclasses import replace

import pytest

from checkout.errors import DomainError
from checkout.flows.airtime import AirtimeFlow
from tests.airtime_support import Unreachable, approve, code_of, paid, quote_input, vtpass_orders
from tests.support import CountingVtpass


class TestMakingAnAirtimeQuote:
    async def test_holds_the_network_number_and_amount_and_reads_them_back(self, stack):
        issued = await stack.airtime.create_airtime_quote(**quote_input(phone="+234 801 111 1111"))
        q = issued.quote
        assert q["phase"] == "awaiting_approval"
        assert q["amount"] == {"kobo": 50_000, "display": "₦500"}
        assert (q["description"], q["merchant"]) == ("MTN airtime", "MTN")
        assert q["details"] == {
            "kind": "airtime",
            "network": "MTN",
            "phone": "0801 111 1111",
            "readBack": "₦500 MTN airtime to 0801 111 1111",
        }
        assert q["mode"]["note"].startswith("Simulated: any Nigerian mobile number is delivered")

    async def test_records_the_quote_in_the_audit_log_with_the_number_masked(self, stack):
        await stack.airtime.create_airtime_quote(**quote_input(phone="08031234567"))
        log = "\n".join(stack.audit_lines)
        assert '"phone_masked": "0803****567"' in log
        assert "08031234567" not in log

    async def test_keeps_the_phone_number_out_of_the_description_that_goes_to_paystack(self, stack):
        issued = await stack.airtime.create_airtime_quote(**quote_input())
        assert not any(
            c.isdigit() and len(run) >= 4 for run in issued.quote["description"].split() for c in run
        )

    @pytest.mark.parametrize(
        "over",
        [
            {"phone": "12345"},
            {"amount_kobo": 50_050, "amount_as_user_said": "₦500.50"},
        ],
        ids=["a number that is not Nigerian", "fractions of a naira"],
    )
    async def test_refuses_bad_input(self, stack, over):
        assert await code_of(stack.airtime.create_airtime_quote(**quote_input(**over))) == "INVALID_INPUT"

    async def test_refuses_a_number_quoted_on_another_network_before_anyone_pays(self, stack):
        refused = stack.airtime.create_airtime_quote(**quote_input(network="airtel", phone="0703 123 4567"))
        assert await code_of(refused) == "INVALID_INPUT"
        with pytest.raises(DomainError, match="0703 123 4567 is a MTN number, not Airtel"):
            await stack.airtime.create_airtime_quote(**quote_input(network="airtel", phone="07031234567"))
        assert await stack.count("quotes") == 0

    async def test_refuses_a_data_number_quoted_on_another_network(self, stack):
        refused = stack.airtime.create_data_quote(
            network="glo", phone="08031234567", plan_code="glo-1gb-300", idempotency_key="data-key-7001"
        )
        assert await code_of(refused) == "INVALID_INPUT"

    @pytest.mark.parametrize("phone", ["08011111111", "201000000000", "100000000000", "0702 123 4567"])
    async def test_a_scenario_number_or_an_unlisted_prefix_names_no_network(self, stack, phone):
        issued = await stack.airtime.create_airtime_quote(**quote_input(network="glo", phone=phone))
        assert issued.quote["phase"] == "awaiting_approval"

    async def test_leaves_the_network_to_the_real_sandbox_in_sandbox_mode(self, stack):
        modes = stack.app.contexts["airtime"].modes
        stack.override("airtime", modes=replace(modes, vtpass="sandbox"))
        issued = await stack.flow("airtime").create_airtime_quote(
            **quote_input(network="airtel", phone="07031234567")
        )
        assert issued.quote["phase"] == "awaiting_approval"
        assert issued.quote["mode"]["note"].startswith("Sandbox: VTpass is sent 08011111111")

    async def test_refuses_a_bad_idempotency_key_before_asking_vtpass(self, stack):
        counting = CountingVtpass(stack.app.contexts["airtime"].vtpass)
        stack.override("airtime", vtpass=counting)
        refused = stack.flow("airtime").create_airtime_quote(**quote_input(idempotency_key="short"))
        assert await code_of(refused) == "INVALID_INPUT"
        assert counting.calls == {}

    async def test_refuses_an_amount_that_does_not_match_the_users_words(self, stack):
        flow = stack.airtime
        assert (
            await code_of(flow.create_airtime_quote(**quote_input(amount_kobo=500_000))) == "AMOUNT_MISMATCH"
        )
        refused = flow.create_airtime_quote(**quote_input(amount_as_user_said="500 or 5000"))
        assert await code_of(refused) == "AMOUNT_UNCLEAR"

    async def test_reads_a_word_amount(self, stack):
        issued = await stack.airtime.create_airtime_quote(
            **quote_input(amount_as_user_said="five hundred naira")
        )
        assert issued.quote["amount"]["kobo"] == 50_000

    async def test_returns_the_same_quote_for_the_same_key(self, stack):
        first = quote_input()
        a = await stack.airtime.create_airtime_quote(**first)
        b = await stack.airtime.create_airtime_quote(**first)
        assert (b.replayed, b.quote["id"]) == (True, a.quote["id"])
        conflict = stack.airtime.create_airtime_quote(**{**first, "phone": "08031234567"})
        assert await code_of(conflict) == "IDEMPOTENCY_CONFLICT"

    async def test_a_replay_still_answers_when_vtpass_is_down(self, stack):
        first = quote_input()
        a = await stack.airtime.create_airtime_quote(**first)
        stack.override("airtime", vtpass=Unreachable())
        b = await stack.flow("airtime").create_airtime_quote(**first)
        assert b.quote["id"] == a.quote["id"]


class TestApprovingAirtime:
    async def test_needs_the_persons_confirmation_of_the_read_back(self, stack):
        flow = stack.airtime
        issued = await flow.create_airtime_quote(**quote_input())

        async def call(confirmed):
            return await flow.approve(issued.quote["id"], issued.approval_token, 50_000, confirmed)

        assert await code_of(call(None)) == "READBACK_REQUIRED"
        assert await code_of(call(False)) == "READBACK_REQUIRED"
        assert (await stack.ledger.get(issued.quote["id"])).state == "open"
        assert (await call(True))["phase"] == "awaiting_checkout"

    async def test_refuses_without_the_cards_token(self, stack):
        issued = await stack.airtime.create_airtime_quote(**quote_input())
        refused = stack.airtime.approve(issued.quote["id"], "no", 50_000, True)
        assert await code_of(refused) == "APPROVAL_DENIED"

    async def test_will_not_approve_a_quote_that_belongs_to_the_payment_connector(self, stack):
        issued = await stack.payments.create_quote(
            amount_kobo=50_000,
            amount_as_user_said="500",
            description="x",
            merchant="y",
            merchant_ref=None,
            idempotency_key="payment-key-9999",
        )
        refused = stack.airtime.approve(issued.quote["id"], issued.approval_token, 50_000, True)
        assert await code_of(refused) == "WRONG_CONNECTOR"


class TestPayingThenDelivery:
    async def test_delivers_only_after_the_payment_is_confirmed_and_shows_a_receipt(self, stack):
        flow = stack.airtime
        issued = await flow.create_airtime_quote(**quote_input())
        view = await approve(flow, issued)
        assert (await flow.verify(issued.quote["id"]))["phase"] == "awaiting_checkout"
        assert await vtpass_orders(stack) == 0

        await stack.complete_checkout(view["checkoutUrl"], "success")
        done = await flow.verify(issued.quote["id"])
        assert (done["phase"], done["receipt"]["title"]) == ("succeeded", "Airtime delivered")
        for line in (
            {"label": "Amount", "value": "₦500"},
            {"label": "Network", "value": "MTN"},
            {"label": "Number", "value": "0801 111 1111"},
        ):
            assert line in done["receipt"]["lines"]
        assert await vtpass_orders(stack) == 1

    async def test_does_not_order_again_once_delivered(self, stack):
        quote_id = await paid(stack)
        for _ in range(3):
            await stack.airtime.verify(quote_id)
        await stack.airtime.status(quote_id)
        assert await vtpass_orders(stack) == 1

    async def test_uses_a_request_id_with_the_lagos_date_and_minute_first_and_keeps_it(self, stack):
        quote_id = await paid(stack)
        await stack.airtime.verify(quote_id)
        request_id = (await stack.ledger.get(quote_id)).progress["fulfilment"]["requestId"]
        assert request_id.startswith("202609291100qt") and len(request_id) == 12 + 2 + 20
        stack.clock.advance(3600)
        await stack.airtime.verify(quote_id)
        assert (await stack.ledger.get(quote_id)).progress["fulfilment"]["requestId"] == request_id

    async def test_does_not_deliver_when_the_checkout_was_declined(self, stack):
        flow = stack.airtime
        issued = await flow.create_airtime_quote(**quote_input())
        view = await approve(flow, issued)
        await stack.complete_checkout(view["checkoutUrl"], "failed")
        assert (await flow.verify(issued.quote["id"]))["phase"] == "failed"
        assert await vtpass_orders(stack) == 0

    async def test_records_a_paid_order_vtpass_could_not_deliver_as_a_refund_due(self, stack):
        quote_id = await paid(stack, phone="100000000000")
        view = await stack.airtime.verify(quote_id)
        assert view["phase"] == "attention"
        assert "VTpass did not deliver: TRANSACTION FAILED." in view["message"]
        assert "Refund due" in view["message"]
        assert "refund.due" in "\n".join(stack.audit_lines)
        assert (await stack.ledger.budget()).spent_today_kobo == 50_000

    @pytest.mark.parametrize(
        ("network", "phone"),
        [
            ("mtn", "0703 123 4567"),
            ("airtel", "0802 123 4567"),
            ("glo", "+234 805 123 4567"),
            ("9mobile", "0809 123 4567"),
        ],
    )
    async def test_delivers_straight_to_a_receipt_for_a_real_looking_number_on_its_network(
        self, stack, network, phone
    ):
        quote_id = await paid(stack, network=network, phone=phone)
        view = await stack.airtime.verify(quote_id)
        assert (view["phase"], view["poll"]) == ("succeeded", False)
        assert view["receipt"]["title"] == "Airtime delivered"
        assert "Refund" not in (view["message"] or "")
        assert "refund.due" not in "\n".join(stack.audit_lines)

    async def test_follows_a_pending_order_until_vtpass_confirms_it(self, stack):
        quote_id = await paid(stack, phone="201000000000")
        first = await stack.airtime.verify(quote_id)
        assert (first["phase"], first["poll"]) == ("processing", True)
        assert "Payment received" in first["message"]
        stack.clock.advance(10)
        assert (await stack.airtime.verify(quote_id))["phase"] == "processing"
        stack.clock.advance(11)
        assert (await stack.airtime.verify(quote_id))["phase"] == "succeeded"
        assert await vtpass_orders(stack) == 1

    @pytest.mark.parametrize("phone", ["500000000000", "400000000000", "300000000000"])
    async def test_treats_an_unexpected_reply_no_reply_and_a_timeout_as_pending_never_failed(
        self, stack, phone
    ):
        quote_id = await paid(stack, phone=phone)
        assert (await stack.airtime.verify(quote_id))["phase"] == "processing"
        stack.clock.advance(21)
        assert (await stack.airtime.verify(quote_id))["phase"] == "succeeded"

    async def test_a_pending_order_is_requeried_not_ordered_again(self, stack):
        quote_id = await paid(stack, phone="201000000000")
        for _ in range(4):
            await stack.airtime.verify(quote_id)
        assert await vtpass_orders(stack) == 1
        assert (await stack.ledger.get(quote_id)).progress["fulfilment"]["attempts"] == 4


class TestData:
    async def test_lists_plans_and_quotes_the_plans_own_price_which_the_model_cannot_change(self, stack):
        plans = await stack.airtime.list_data_plans("mtn")
        assert "mtn-10mb-100" in [p.code for p in plans]
        issued = await stack.airtime.create_data_quote(
            network="mtn", phone="08011111111", plan_code="mtn-100mb-1000", idempotency_key="data-key-0001"
        )
        q = issued.quote
        assert q["amount"] == {"kobo": 100_000, "display": "₦1,000"}
        assert (q["details"]["kind"], q["details"]["plan"]) == ("data", "N1000 1.5GB - 30 days")

    async def test_refuses_a_plan_code_the_network_does_not_have(self, stack):
        refused = stack.airtime.create_data_quote(
            network="mtn", phone="08011111111", plan_code="nope", idempotency_key="data-key-0002"
        )
        assert await code_of(refused) == "INVALID_INPUT"

    async def test_buys_the_plan_after_payment(self, stack):
        flow = stack.airtime
        issued = await flow.create_data_quote(
            network="mtn", phone="08011111111", plan_code="mtn-10mb-100", idempotency_key="data-key-0003"
        )
        view = await approve(flow, issued, 10_000)
        await stack.complete_checkout(view["checkoutUrl"], "success")
        done = await flow.verify(issued.quote["id"])
        assert done["receipt"]["title"] == "Data delivered"
        assert {"label": "Plan", "value": "N100 100MB - 24 hrs"} in done["receipt"]["lines"]

    async def test_a_provider_that_lists_no_plans_is_a_provider_error(self, stack):
        class NoPlans:
            async def data_plans(self, network):
                from checkout.vtpass.api import VtpassError

                raise VtpassError("VTpass did not return a list of data plans.")

        flow = AirtimeFlow(replace(stack.app.contexts["airtime"], vtpass=NoPlans()))
        assert await code_of(flow.list_data_plans("mtn")) == "PROVIDER_ERROR"
