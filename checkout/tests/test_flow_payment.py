# SPDX-License-Identifier: AGPL-3.0-or-later
"""The payment flow, ported from the TypeScript demo's payment-flow.test.ts."""

import asyncio
import json
from dataclasses import replace

import pytest

from checkout.config import Settings
from checkout.errors import DomainError
from checkout.flows.payment import PaymentFlow
from checkout.ledger import NewQuote
from checkout.paystack.api import PaystackError
from tests.support import make_stack

_counter = 0


def quote_input(**over):
    global _counter
    _counter += 1
    return {
        "amount_kobo": 500_000,
        "amount_as_user_said": "five thousand naira",
        "description": "Lunch at Demo Kitchen",
        "merchant": "Demo Kitchen",
        "merchant_ref": "order-42",
        "idempotency_key": f"payment-key-{_counter:04d}",
        **over,
    }


async def code_of(work) -> str:
    try:
        await work
    except DomainError as error:
        return error.code
    return "none"


@pytest.fixture
def flow(stack) -> PaymentFlow:
    return stack.payments


async def approve(flow, issued, amount=500_000, token=None):
    return await flow.approve(issued.quote["id"], token or issued.approval_token, amount)


class TestMakingAQuote:
    async def test_holds_the_amount_and_description_itself_and_shows_them_back_from_the_store(self, flow):
        issued = await flow.create_quote(**quote_input())
        q = issued.quote
        assert (q["phase"], q["amount"], q["description"], q["merchant"], q["merchantRef"]) == (
            "awaiting_approval",
            {"kobo": 500_000, "display": "₦5,000"},
            "Lunch at Demo Kitchen",
            "Demo Kitchen",
            "order-42",
        )
        assert q["limits"] == {"perPayment": "₦50,000", "daily": "₦100,000", "remainingToday": "₦100,000"}
        assert q["mode"] == {"label": "Simulated: no money moves", "simulated": True, "note": None}
        assert len(issued.approval_token) == 64
        assert issued.approval_token not in json.dumps(q)

    async def test_refuses_an_amount_that_does_not_match_what_the_user_said(self, flow):
        assert await code_of(flow.create_quote(**quote_input(amount_kobo=5_000_000))) == "AMOUNT_MISMATCH"
        assert (
            await code_of(flow.create_quote(**quote_input(amount_as_user_said="5k or 50k")))
            == "AMOUNT_UNCLEAR"
        )

    async def test_refuses_an_amount_above_the_per_payment_limit(self, flow):
        refused = flow.create_quote(**quote_input(amount_kobo=6_000_000, amount_as_user_said="60k"))
        assert await code_of(refused) == "LIMIT_PER_PAYMENT"

    async def test_returns_the_same_quote_for_a_repeated_idempotency_key(self, flow):
        first = quote_input()
        a, b = await flow.create_quote(**first), await flow.create_quote(**first)
        assert (b.replayed, b.quote["id"], b.approval_token) == (True, a.quote["id"], a.approval_token)

    async def test_refuses_the_same_key_for_a_different_request(self, flow):
        first = quote_input()
        await flow.create_quote(**first)
        assert (
            await code_of(flow.create_quote(**{**first, "description": "Dinner"})) == "IDEMPOTENCY_CONFLICT"
        )

    async def test_records_the_quote_in_the_audit_log_without_the_token(self, stack, flow):
        issued = await flow.create_quote(**quote_input())
        events = [json.loads(line) for line in stack.audit_lines]
        created = next(e for e in events if e["event"] == "quote.created")
        assert (created["quote"], created["kind"], created["amount_kobo"]) == (
            issued.quote["id"],
            "payment",
            500_000,
        )
        assert issued.approval_token not in "\n".join(stack.audit_lines)

    async def test_records_a_refused_quote_and_why(self, stack, flow):
        await code_of(flow.create_quote(**quote_input(amount_kobo=5_000_000)))
        refused = [json.loads(line) for line in stack.audit_lines if "quote.rejected" in line]
        assert refused and refused[0]["code"] == "AMOUNT_MISMATCH"

    async def test_refuses_a_merchant_reference_with_odd_characters(self, flow):
        assert await code_of(flow.create_quote(**quote_input(merchant_ref="<script>"))) == "INVALID_INPUT"


class TestApprovingAndPaying:
    async def test_runs_the_whole_path_approve_open_the_checkout_pay_verify_receipt(self, stack, flow):
        issued = await flow.create_quote(**quote_input())
        approved = await approve(flow, issued)
        assert (approved["phase"], approved["poll"]) == ("awaiting_checkout", True)
        assert approved["checkoutUrl"].startswith("http://localhost:8787/sim/checkout/qt-")

        assert (await flow.verify(issued.quote["id"]))["phase"] == "awaiting_checkout"
        await stack.complete_checkout(approved["checkoutUrl"], "success")

        done = await flow.verify(issued.quote["id"])
        assert (done["phase"], done["poll"], done["receipt"]["title"]) == (
            "succeeded",
            False,
            "Payment received",
        )
        lines = done["receipt"]["lines"]
        for expected in (
            {"label": "Amount", "value": "₦5,000"},
            {"label": "For", "value": "Lunch at Demo Kitchen"},
            {"label": "Mode", "value": "Simulated: no money moves"},
        ):
            assert expected in lines
        events = {json.loads(line)["event"] for line in stack.audit_lines}
        assert {"quote.created", "approval.claimed", "checkout.started", "payment.settled"} <= events

    async def test_refuses_an_approval_without_the_cards_token_and_reserves_no_spend(self, stack, flow):
        issued = await flow.create_quote(**quote_input())
        assert await code_of(approve(flow, issued, token="guess")) == "APPROVAL_DENIED"
        assert (await stack.ledger.budget()).spent_today_kobo == 0
        assert (await stack.ledger.get(issued.quote["id"])).state == "open"

    async def test_refuses_an_approval_when_the_card_showed_a_different_amount(self, stack, flow):
        issued = await flow.create_quote(**quote_input())
        assert await code_of(approve(flow, issued, amount=50_000)) == "AMOUNT_MISMATCH"
        assert (await stack.ledger.get(issued.quote["id"])).state == "open"

    async def test_gives_the_same_checkout_for_a_repeated_approval_and_reserves_the_spend_once(
        self, stack, flow
    ):
        issued = await flow.create_quote(**quote_input())
        a, b = await approve(flow, issued), await approve(flow, issued)
        assert b["checkoutUrl"] == a["checkoutUrl"]
        assert (await stack.ledger.budget()).spent_today_kobo == 500_000

    async def test_does_not_start_two_checkouts_when_two_approvals_race(self, stack, flow):
        issued = await flow.create_quote(**quote_input())
        results = await asyncio.gather(approve(flow, issued), approve(flow, issued), return_exceptions=True)
        assert sum(isinstance(r, dict) for r in results) == 1
        refused = next(r for r in results if isinstance(r, Exception))
        assert getattr(refused, "code", None) == "APPROVAL_IN_PROGRESS"
        assert "paystackReference" in (await stack.ledger.get(issued.quote["id"])).progress

    async def test_refuses_an_approval_once_the_quote_has_expired(self, stack, flow):
        issued = await flow.create_quote(**quote_input())
        stack.clock.advance(11 * 60)
        assert await code_of(approve(flow, issued)) == "QUOTE_EXPIRED"
        assert (await flow.status(issued.quote["id"]))["phase"] == "expired"

    async def test_stops_at_the_daily_limit(self):
        stack = make_stack(per_payment_limit_kobo=4_000_000, daily_limit_kobo=6_000_000)
        flow = stack.payments
        first = await flow.create_quote(**quote_input(amount_kobo=4_000_000, amount_as_user_said="40k"))
        second = await flow.create_quote(**quote_input(amount_kobo=4_000_000, amount_as_user_said="40k"))
        await approve(flow, first, 4_000_000)
        assert await code_of(approve(flow, second, 4_000_000)) == "LIMIT_DAILY"

    async def test_will_not_let_an_airtime_quote_be_approved_here(self, stack, flow):
        foreign, _ = await stack.ledger.create(
            NewQuote(
                "airtime",
                "airtime",
                50_000,
                "Airtime",
                "MTN",
                None,
                {"kind": "airtime", "network": "mtn", "phone": "08011111111"},
                "foreign-key-0001",
                "h",
            )
        )
        token = stack.ledger.approval_token(foreign.id)
        assert await code_of(flow.approve(foreign.id, token, 50_000)) == "WRONG_CONNECTOR"

    async def test_puts_the_approval_back_when_paystack_cannot_start_the_checkout(self, stack, flow):
        issued = await flow.create_quote(**quote_input())

        class Down:
            async def initialize_transaction(self, request):
                raise PaystackError("down", retryable=True)

        broken = PaymentFlow(replace(stack.app.contexts["paystack-pay"], paystack=Down()))
        assert await code_of(approve(broken, issued)) == "PROVIDER_ERROR"
        assert (await stack.ledger.get(issued.quote["id"])).state == "open"
        assert (await stack.ledger.budget()).spent_today_kobo == 0
        again = await approve(flow, issued)
        assert again["phase"] == "awaiting_checkout"
        assert (await stack.ledger.get(issued.quote["id"])).progress["paystackReference"].endswith("-a2")


class TestAtTheCheckout:
    async def approved(self, flow):
        issued = await flow.create_quote(**quote_input())
        view = await approve(flow, issued)
        return issued, view["checkoutUrl"]

    async def test_reports_a_declined_card_as_failed_and_frees_the_spend(self, stack, flow):
        issued, url = await self.approved(flow)
        await stack.complete_checkout(url, "failed")
        view = await flow.verify(issued.quote["id"])
        assert view["phase"] == "failed" and "Nothing was charged" in view["message"]
        assert (await stack.ledger.budget()).spent_today_kobo == 0

    async def test_does_not_give_up_while_the_checkout_is_merely_unpaid(self, stack, flow):
        issued, _ = await self.approved(flow)
        assert (await flow.verify(issued.quote["id"]))["phase"] == "awaiting_checkout"
        stack.clock.advance(5 * 60)
        assert (await flow.verify(issued.quote["id"]))["phase"] == "awaiting_checkout"

    async def test_gives_up_when_the_person_says_they_closed_the_checkout(self, stack, flow):
        issued, _ = await self.approved(flow)
        view = await flow.verify(issued.quote["id"], checkout_closed=True)
        assert view["phase"] == "abandoned"
        assert (await stack.ledger.budget()).spent_today_kobo == 0

    async def test_does_not_give_up_on_a_checkout_that_is_being_paid_even_when_told_it_was_closed(
        self, stack, flow
    ):
        issued, url = await self.approved(flow)
        await stack.open_checkout(url)
        assert (await flow.verify(issued.quote["id"], checkout_closed=True))["phase"] == "awaiting_checkout"

    async def test_gives_up_after_the_checkout_window(self, stack, flow):
        issued, _ = await self.approved(flow)
        stack.clock.advance(16 * 60)
        assert (await flow.verify(issued.quote["id"]))["phase"] == "abandoned"

    async def test_keeps_a_payment_that_lands_after_the_quote_was_given_up_on_as_a_refund_due(
        self, stack, flow
    ):
        issued, url = await self.approved(flow)
        await flow.verify(issued.quote["id"], checkout_closed=True)
        await stack.complete_checkout(url, "success")
        view = await flow.verify(issued.quote["id"])
        assert view["phase"] == "attention" and "Refund due" in view["message"]
        assert (await stack.ledger.budget()).spent_today_kobo == 500_000

    async def test_marks_a_payment_for_the_wrong_amount_as_a_refund_due_not_as_paid(self, stack, flow):
        issued, url = await self.approved(flow)
        await stack.complete_checkout(url, "success")
        await stack.db.execute(
            "UPDATE sim_transactions SET amount_kobo = 100 WHERE reference = ?", url.rsplit("/", 1)[1]
        )
        view = await flow.verify(issued.quote["id"])
        assert view["phase"] == "attention"
        assert "₦1 NGN paid for a ₦5,000 quote" in view["message"]

    async def test_lets_the_person_decline_an_open_quote_and_then_refuses_to_approve_it(self, flow):
        issued = await flow.create_quote(**quote_input())
        assert (await flow.decline(issued.quote["id"], issued.approval_token))["phase"] == "declined"
        assert await code_of(approve(flow, issued)) == "QUOTE_NOT_OPEN"

    async def test_refuses_a_decline_without_the_token(self, flow):
        issued = await flow.create_quote(**quote_input())
        assert await code_of(flow.decline(issued.quote["id"], "no")) == "APPROVAL_DENIED"

    async def test_a_payment_settles_once_however_many_check_together(self, stack, flow):
        issued, url = await self.approved(flow)
        await stack.complete_checkout(url, "success")
        views = await asyncio.gather(*[flow.verify(issued.quote["id"]) for _ in range(10)])
        assert {v["phase"] for v in views} == {"succeeded"}
        assert await stack.count("quotes") == 1
        assert sum(1 for line in stack.audit_lines if "payment.settled" in line) >= 1


def test_settings_are_frozen_so_a_test_cannot_change_them_by_accident():
    settings = Settings(approval_secret="x")
    with pytest.raises(AttributeError):
        settings.daily_limit_kobo = 1  # type: ignore[misc]
