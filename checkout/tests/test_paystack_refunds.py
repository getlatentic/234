# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paystack's Refund API (https://paystack.com/docs/api/refund/) through the real client: on a scripted
transport, the calls and reply shapes as documented; on the simulator, a refund of a paid transaction queued
`pending`, never more than the payment, and listed by the transaction's id."""

import pytest

from checkout.paystack.api import CheckoutRequest, PaystackError, RefundRequest
from checkout.paystack.client import PaystackClient
from tests.keys import fake_key
from tests.support import ScriptedTransport, json_reply, make_stack

KEY = fake_key("test", "unittestkey0001")
CREATED = {
    "transaction": {"id": 1004723697, "reference": "qt-1-a1", "amount": 50_000, "currency": "NGN"},
    "integration": 412829,
    "deducted_amount": 0,
    "status": "pending",
    "currency": "NGN",
    "amount": 50_000,
    "id": 3018284,
}
FETCHED = {
    "transaction": 1004723697,
    "amount": 50_000,
    "currency": "NGN",
    "status": "processed",
    "id": 3018284,
}


def client_with(answer):
    transport = ScriptedTransport(answer)
    return PaystackClient(KEY, transport), transport


class TestTheClient:
    async def test_creates_a_refund_of_the_amount_against_the_reference(self):
        client, transport = client_with(
            lambda _: json_reply({"status": True, "message": "Refund has been queued", "data": CREATED})
        )
        outcome = await client.create_refund(RefundRequest("qt-1-a1", 50_000, "234 quote qt-1", "Refund"))
        sent = transport.calls[0]
        assert (sent.method, sent.url) == ("POST", "https://api.paystack.co/refund")
        assert sent.body == {
            "transaction": "qt-1-a1",
            "amount": 50_000,
            "currency": "NGN",
            "merchant_note": "234 quote qt-1",
            "customer_note": "Refund",
        }
        assert (outcome.refund_id, outcome.status, outcome.amount_kobo, outcome.transaction_id) == (
            3018284,
            "pending",
            50_000,
            1004723697,
        )

    async def test_fetches_one_and_lists_a_transactions_refunds(self):
        def answer(sent):
            data = FETCHED if sent.url.endswith("/refund/3018284") else [FETCHED]
            return json_reply({"status": True, "message": "Refund retrieved", "data": data})

        client, transport = client_with(answer)
        fetched = await client.fetch_refund(3018284)
        listed = await client.refunds_of(1004723697)
        assert (fetched.status, fetched.transaction_id) == ("processed", 1004723697)
        assert listed == [fetched]
        assert transport.calls[1].url == "https://api.paystack.co/refund?transaction=1004723697"

    async def test_reads_a_status_it_does_not_know_as_it_is(self):
        client, _ = client_with(
            lambda _: json_reply({"status": True, "data": {**FETCHED, "status": "reversal-queued"}})
        )
        assert (await client.fetch_refund(3018284)).status == "reversal-queued"

    async def test_a_refusal_is_not_retryable_and_a_server_error_is(self):
        client, _ = client_with(lambda _: json_reply({"status": False, "message": "Fully reversed"}, 400))
        with pytest.raises(PaystackError) as refused:
            await client.create_refund(RefundRequest("qt-1-a1", 50_000, "n", "n"))
        assert not refused.value.retryable
        client, _ = client_with(lambda _: json_reply({"status": False, "message": "Down"}, 502))
        with pytest.raises(PaystackError) as down:
            await client.create_refund(RefundRequest("qt-1-a1", 50_000, "n", "n"))
        assert down.value.retryable


async def _paid(api, stack, reference: str = "qt-00000000000000000001-a1"):
    await api.initialize_transaction(CheckoutRequest(50_000, "demo@example.com", reference, "qt-1", "Lunch"))
    await stack.complete_checkout(f"/sim/checkout/{reference}")
    return await api.verify_transaction(reference)


class TestTheSimulator:
    async def test_verifying_a_payment_names_its_transaction(self):
        stack = make_stack()
        api = stack.app.contexts["paystack-pay"].paystack
        check = await _paid(api, stack)
        assert isinstance(check.transaction_id, int)

    async def test_queues_a_refund_and_lists_it_by_the_transaction(self):
        stack = make_stack()
        api = stack.app.contexts["paystack-pay"].paystack
        check = await _paid(api, stack)
        made = await api.create_refund(RefundRequest(check.reference, 50_000, "n", "n"))
        assert (made.status, made.transaction_id) == ("pending", check.transaction_id)
        assert await api.refunds_of(check.transaction_id) == [made]
        assert await api.fetch_refund(made.refund_id) == made

    async def test_never_refunds_more_than_the_payment(self):
        stack = make_stack()
        api = stack.app.contexts["paystack-pay"].paystack
        check = await _paid(api, stack)
        await api.create_refund(RefundRequest(check.reference, 30_000, "n", "n"))
        with pytest.raises(PaystackError, match="more than the transaction amount"):
            await api.create_refund(RefundRequest(check.reference, 30_000, "n", "n"))

    async def test_refunds_only_a_paid_transaction(self):
        stack = make_stack()
        api = stack.app.contexts["paystack-pay"].paystack
        reference = "qt-00000000000000000002-a1"
        await api.initialize_transaction(
            CheckoutRequest(50_000, "demo@example.com", reference, "qt-2", "Lunch")
        )
        with pytest.raises(PaystackError, match="not been completed"):
            await api.create_refund(RefundRequest(reference, 50_000, "n", "n"))
        with pytest.raises(PaystackError, match="not found"):
            await api.create_refund(RefundRequest("qt-unknown-a1", 50_000, "n", "n"))

    async def test_where_test_routes_are_on_a_refund_waits_for_them(self):
        stack = make_stack()
        api = stack.app.contexts["paystack-pay"].paystack
        check = await _paid(api, stack)
        made = await api.create_refund(RefundRequest(check.reference, 50_000, "n", "n"))
        assert (await api.fetch_refund(made.refund_id)).status == "pending"

    async def test_where_they_are_off_a_refund_is_processed_when_234_asks(self):
        stack = make_stack(enable_test_routes=False)
        api = stack.app.contexts["paystack-pay"].paystack
        check = await _paid(api, stack)
        made = await api.create_refund(RefundRequest(check.reference, 50_000, "n", "n"))
        assert made.status == "pending"
        assert (await api.fetch_refund(made.refund_id)).status == "processed"
        assert [r.status for r in await api.refunds_of(check.transaction_id)] == ["processed"]
