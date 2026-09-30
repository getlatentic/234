# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated Paystack through the real client, ported from the TypeScript demo's simulator.test.ts."""

import pytest

from checkout.config import SimulatorSettings
from checkout.http import handle
from checkout.paystack.api import (
    AccountLookup,
    CheckoutRequest,
    PaystackError,
    RecipientRequest,
    TransferRequest,
)
from checkout.paystack.sim import PAYSTACK_TEST_ACCOUNT, SIMULATED_OTP
from tests.support import make_stack

ACCOUNT = AccountLookup(PAYSTACK_TEST_ACCOUNT, "057")
REF = "trf-qt-0000000000000001"


def paystack_of(**simulator):
    stack = make_stack(simulator=SimulatorSettings(**simulator))
    return stack, stack.app.contexts["paystack-pay"].paystack


def checkout_request(reference: str, **over) -> CheckoutRequest:
    fields = {"amount_kobo": 250_000, "email": "demo@example.com", "reference": reference, "quote_id": "qt-1",
              "description": "Lunch at Demo Kitchen", **over}  # fmt: skip
    return CheckoutRequest(**fields)


async def recipient_for(api):
    name = await api.resolve_account(ACCOUNT)
    return await api.create_recipient(RecipientRequest(name, ACCOUNT.account_number, ACCOUNT.bank_code))


class TestTransactions:
    async def test_initializes_a_checkout_on_the_worker_and_verifies_each_outcome(self):
        stack, api = paystack_of()
        checkout = await api.initialize_transaction(checkout_request("ref-success-1"))
        assert checkout.authorization_url == "http://localhost:8787/sim/checkout/ref-success-1"
        assert (await api.verify_transaction("ref-success-1")).status == "abandoned"
        await stack.complete_checkout(checkout.authorization_url, "success")
        paid = await api.verify_transaction("ref-success-1")
        assert (paid.status, paid.amount_kobo, paid.currency, paid.gateway_response) == (
            "success", 250_000, "NGN", "Successful",
        )  # fmt: skip
        assert paid.paid_at == "2026-09-29T10:00:00.000Z"

    async def test_reports_ongoing_once_the_page_is_open_failed_on_a_decline_and_abandoned_when_closed(self):
        stack, api = paystack_of()
        opened = await api.initialize_transaction(checkout_request("ref-open-1"))
        await stack.open_checkout(opened.authorization_url)
        assert (await api.verify_transaction("ref-open-1")).status == "ongoing"
        declined = await api.initialize_transaction(checkout_request("ref-decline-1"))
        await stack.complete_checkout(declined.authorization_url, "failed")
        assert (await api.verify_transaction("ref-decline-1")).status == "failed"
        closed = await api.initialize_transaction(checkout_request("ref-close-1"))
        await stack.complete_checkout(closed.authorization_url, "abandoned")
        assert (await api.verify_transaction("ref-close-1")).status == "abandoned"

    async def test_reports_failed_on_a_decline(self):
        stack, api = paystack_of()
        declined = await api.initialize_transaction(checkout_request("ref-decline-1"))
        await stack.complete_checkout(declined.authorization_url, "failed")
        assert (await api.verify_transaction("ref-decline-1")).status == "failed"

    async def test_a_finished_payment_is_not_changed_by_a_second_click(self):
        stack, api = paystack_of()
        checkout = await api.initialize_transaction(checkout_request("ref-final-1"))
        await stack.complete_checkout(checkout.authorization_url, "success")
        await stack.complete_checkout(checkout.authorization_url, "failed")
        assert (await api.verify_transaction("ref-final-1")).status == "success"

    async def test_refuses_a_duplicate_reference_as_paystack_does(self):
        _, api = paystack_of()
        await api.initialize_transaction(checkout_request("ref-dup-1"))
        with pytest.raises(PaystackError, match="Duplicate Transaction Reference") as refused:
            await api.initialize_transaction(checkout_request("ref-dup-1"))
        assert not refused.value.retryable

    @pytest.mark.parametrize(
        "over",
        [{"reference": "bad_ref!"}, {"email": "nope"}, {"amount_kobo": 0}],
        ids=["a reference with a bad character", "an email without @", "a zero amount"],
    )
    async def test_refuses_bad_input(self, over):
        _, api = paystack_of()
        with pytest.raises(PaystackError):
            await api.initialize_transaction(checkout_request(**{"reference": "ref-bad-1", **over}))

    async def test_refuses_an_unknown_reference(self):
        _, api = paystack_of()
        with pytest.raises(PaystackError, match="not found"):
            await api.verify_transaction("missing-ref")


class TestCheckoutPage:
    async def test_labels_itself_as_simulated_and_shows_the_amount_and_what_it_is_for(self):
        stack, api = paystack_of()
        await api.initialize_transaction(checkout_request("ref-page-1"))
        page = await handle(stack.app, "GET", "/sim/checkout/ref-page-1", {}, b"")
        assert page.status == 200
        assert "Simulated: no money moves" in page.body
        assert "₦2,500" in page.body
        assert "Lunch at Demo Kitchen" in page.body

    async def test_escapes_what_the_model_wrote(self):
        stack, api = paystack_of()
        await api.initialize_transaction(
            checkout_request("ref-xss-1", description="<script>alert(1)</script>")
        )
        page = await handle(stack.app, "GET", "/sim/checkout/ref-xss-1", {}, b"")
        assert "<script>alert" not in page.body

    async def test_refuses_an_outcome_posted_from_another_origin(self):
        stack, api = paystack_of()
        await api.initialize_transaction(checkout_request("ref-origin-1"))
        refused = await handle(
            stack.app, "POST", "/sim/checkout/ref-origin-1/pay", {"origin": "https://evil.example"}, b""
        )
        assert refused.status == 403
        assert (await api.verify_transaction("ref-origin-1")).status == "abandoned"

    async def test_accepts_an_outcome_posted_from_the_page_itself(self):
        stack, api = paystack_of()
        await api.initialize_transaction(checkout_request("ref-same-1"))
        accepted = await handle(
            stack.app, "POST", "/sim/checkout/ref-same-1/pay", {"origin": "http://localhost:8787"}, b""
        )
        assert accepted.status == 200
        assert (await api.verify_transaction("ref-same-1")).status == "success"

    async def test_answers_404_for_an_unknown_checkout(self):
        stack, _ = paystack_of()
        assert (await handle(stack.app, "GET", "/sim/checkout/deadbeef", {}, b"")).status == 404


class TestTransfers:
    async def test_resolves_the_documented_test_account_and_creates_a_recipient_with_a_bank_name(self):
        _, api = paystack_of()
        assert await api.resolve_account(ACCOUNT) == "PAYSTACK TEST ACCOUNT"
        recipient = await recipient_for(api)
        assert (recipient.name, recipient.bank_name) == ("PAYSTACK TEST ACCOUNT", "Zenith Bank")

    async def test_returns_the_existing_recipient_for_a_duplicate_account(self):
        _, api = paystack_of()
        assert (await recipient_for(api)).recipient_code == (await recipient_for(api)).recipient_code

    async def test_names_other_ten_digit_accounts_and_refuses_the_ones_it_cannot_resolve(self):
        _, api = paystack_of()
        assert await api.resolve_account(AccountLookup("0123456789", "058")) == "SIMULATED ACCOUNT 6789"
        for number in ("1234", "9999123456", "abcdefghij"):
            with pytest.raises(PaystackError, match="Could not resolve"):
                await api.resolve_account(AccountLookup(number, "058"))

    async def test_succeeds_at_once_as_paystack_test_transfers_do(self):
        _, api = paystack_of()
        recipient = await recipient_for(api)
        outcome = await api.initiate_transfer(TransferRequest(100_000, recipient.recipient_code, REF, "Rent"))
        assert (outcome.status, outcome.reference, outcome.amount_kobo) == ("success", REF, 100_000)
        assert (await api.verify_transfer(REF)).status == "success"

    async def test_a_repeat_of_the_same_transfer_is_the_same_transfer_and_a_changed_one_is_refused(self):
        _, api = paystack_of()
        recipient = await recipient_for(api)
        request = TransferRequest(100_000, recipient.recipient_code, REF, "Rent")
        first = await api.initiate_transfer(request)
        assert (await api.initiate_transfer(request)).transfer_code == first.transfer_code
        with pytest.raises(PaystackError, match="different transfer"):
            await api.initiate_transfer(TransferRequest(200_000, recipient.recipient_code, REF, "Rent"))

    async def test_refuses_an_unknown_recipient_and_a_malformed_reference(self):
        _, api = paystack_of()
        with pytest.raises(PaystackError, match="Recipient"):
            await api.initiate_transfer(TransferRequest(1, "RCP_none", REF, "x"))
        recipient = await recipient_for(api)
        with pytest.raises(PaystackError, match="reference"):
            await api.initiate_transfer(TransferRequest(1, recipient.recipient_code, "short", "x"))

    async def test_asks_for_an_otp_when_the_account_requires_one_and_completes_with_the_right_one(self):
        _, api = paystack_of(transfer_otp=True)
        recipient = await recipient_for(api)
        started = await api.initiate_transfer(TransferRequest(100_000, recipient.recipient_code, REF, "Rent"))
        assert started.status == "otp"
        with pytest.raises(PaystackError, match="Invalid OTP"):
            await api.finalize_transfer(started.transfer_code, "000000")
        assert (await api.verify_transfer(REF)).status == "otp"
        assert (await api.finalize_transfer(started.transfer_code, SIMULATED_OTP)).status == "success"
        assert (await api.verify_transfer(REF)).status == "success"

    async def test_refuses_every_transfer_as_paystack_does_for_a_starter_business_when_asked_to(self):
        _, api = paystack_of(payouts_refused=True)
        recipient = await recipient_for(api)
        with pytest.raises(PaystackError, match="third party payouts as a starter business") as refused:
            await api.initiate_transfer(TransferRequest(100_000, recipient.recipient_code, REF, "Rent"))
        assert not refused.value.retryable

    async def test_refuses_to_finalize_a_transfer_that_needs_no_otp(self):
        _, api = paystack_of()
        recipient = await recipient_for(api)
        started = await api.initiate_transfer(TransferRequest(100_000, recipient.recipient_code, REF, "Rent"))
        with pytest.raises(PaystackError, match="not awaiting"):
            await api.finalize_transfer(started.transfer_code, SIMULATED_OTP)

    async def test_a_key_that_is_not_a_test_key_is_refused_by_the_simulator_too(self):
        stack, _ = paystack_of()
        from checkout.paystack.sim import PaystackSimulator
        from checkout.paystack.sim_store import PaystackSimStore

        simulator = PaystackSimulator(PaystackSimStore(stack.db), "http://x/sim/checkout")
        reply = await simulator.send(
            "GET",
            "https://api.paystack.co/transaction/verify/r",
            headers={"Authorization": "Bearer nope"},
            body=None,
            timeout_seconds=1,
        )
        assert reply.status == 401
