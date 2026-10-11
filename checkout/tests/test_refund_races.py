# SPDX-License-Identifier: AGPL-3.0-or-later
"""A refund is sent once (refunds/opening.py, refunds/outcome.py): however many callers race to open it, a
lost reply is never sent again while Paystack holds a refund of the payment, a send in flight is left alone,
and a refund Paystack never had is sent again only once the lost send is old and Paystack lists none."""

import asyncio

import pytest

from checkout.paystack.api import PaystackError, RefundOutcome, RefundRequest
from tests.refund_support import (
    audited,
    owed,
    paystack_of,
    refund_of,
    refunds,
    sim_refunds,
    sweep,
    with_paystack,
)
from tests.support import PaystackOverride


async def lost_reply(stack, reached: bool):
    """An owed refund whose send got no answer: `reached` says whether Paystack made the refund anyway."""
    inner = paystack_of(stack)
    paystack = PaystackOverride(inner)

    async def lost(request):
        if reached:
            await inner.create_refund(request)
        raise PaystackError("Paystack could not be reached.", retryable=True)

    paystack._replacements["create_refund"] = lost
    with_paystack(stack, paystack)
    quote_id = await owed(stack)
    await stack.run_jobs()
    paystack._replacements.pop("create_refund")
    return quote_id, paystack


class TestOnce:
    async def test_callers_racing_to_open_it_send_one_refund(self, stack):
        paystack = PaystackOverride(paystack_of(stack))
        with_paystack(stack, paystack)
        quote_id = await owed(stack)
        stack.jobs.held.clear()
        await asyncio.gather(*[refunds(stack).follow(quote_id) for _ in range(8)])
        assert paystack.calls["create_refund"] == 1
        assert len(await sim_refunds(stack)) == 1
        assert (await refund_of(stack, quote_id)).state == "sent"

    async def test_the_job_the_minute_and_an_event_together_send_one_refund(self, stack):
        quote_id = await owed(stack)
        stack.clock.advance(60)
        await asyncio.gather(stack.run_jobs(), stack.app.background.minute(), refunds(stack).follow(quote_id))
        await stack.run_jobs()
        assert len(await sim_refunds(stack)) == 1

    async def test_paystack_itself_never_refunds_more_than_the_payment(self, stack):
        quote_id = await owed(stack)
        await stack.run_jobs()
        refund = await refund_of(stack, quote_id)
        request = RefundRequest(refund.transaction_reference, refund.amount_kobo, "again", "again")
        with pytest.raises(PaystackError, match="more than the transaction amount"):
            await paystack_of(stack).create_refund(request)
        assert len(await sim_refunds(stack)) == 1


class TestALostReply:
    async def test_stays_undecided_with_its_send_held(self, stack):
        quote_id, _ = await lost_reply(stack, reached=True)
        refund = await refund_of(stack, quote_id)
        assert (refund.state, refund.refund_id) == ("sent", None)
        assert refund.sending_since is not None
        assert audited(stack, "refund.undecided") == 1

    async def test_paystack_holding_the_refund_is_found_not_sent_again(self, stack):
        quote_id, paystack = await lost_reply(stack, reached=True)
        await sweep(stack, 120)
        assert paystack.calls["create_refund"] == 1
        assert len(await sim_refunds(stack)) == 1
        refund = await refund_of(stack, quote_id)
        assert (refund.state, refund.refund_status, refund.refund_id) == (
            "sent",
            "pending",
            (await sim_refunds(stack))[0]["id"],
        )

    async def test_one_paystack_never_had_is_not_sent_again_while_the_lost_send_is_fresh(self, stack):
        _, paystack = await lost_reply(stack, reached=False)
        await sweep(stack, 31)
        assert paystack.calls["create_refund"] == 1
        assert await sim_refunds(stack) == []

    async def test_then_once_it_is_old_it_is_sent_again_once(self, stack):
        quote_id, paystack = await lost_reply(stack, reached=False)
        await sweep(stack, 120)
        await sweep(stack, 120)
        assert paystack.calls["create_refund"] == 2
        assert len(await sim_refunds(stack)) == 1
        assert (await refund_of(stack, quote_id)).refund_status == "pending"

    async def test_a_list_paystack_did_not_answer_is_never_taken_for_none(self, stack):
        _, paystack = await lost_reply(stack, reached=False)

        async def unreachable(transaction_id):
            raise PaystackError("Paystack could not be reached.", retryable=True)

        paystack._replacements["refunds_of"] = unreachable
        await sweep(stack, 3600)
        assert paystack.calls["create_refund"] == 1
        assert await sim_refunds(stack) == []


class TestAnAnswerForAnotherRefund:
    async def test_decides_nothing_and_keeps_the_send(self, stack):
        async def odd(request):
            return RefundOutcome(1234, "processed", 100, "NGN", None)

        with_paystack(stack, PaystackOverride(paystack_of(stack), create_refund=odd))
        quote_id = await owed(stack)
        await stack.run_jobs()
        refund = await refund_of(stack, quote_id)
        assert (refund.state, refund.refund_id) == ("sent", None)
        assert (await stack.ledger.get(quote_id)).state == "refund_due"
        assert audited(stack, "refund.mismatch") == 1


class TestARefusal:
    async def test_is_asked_about_once_more_and_fails_when_paystack_holds_none(self, stack):
        async def refused(request):
            raise PaystackError("Transaction has been fully reversed", retryable=False, http_status=400)

        paystack = PaystackOverride(paystack_of(stack), create_refund=refused)
        with_paystack(stack, paystack)
        quote_id = await owed(stack)
        await stack.run_jobs()
        assert paystack.calls["refunds_of"] == 1
        refund = await refund_of(stack, quote_id)
        assert refund.state == "failed" and refund.refund_status.startswith("refused")
        assert audited(stack, "refund.failed") == 1

    async def test_for_a_refund_paystack_already_holds_is_not_a_failure(self, stack):
        inner = paystack_of(stack)

        async def duplicate(request):
            await inner.create_refund(request)
            raise PaystackError("Duplicate refund", retryable=False, http_status=400)

        with_paystack(stack, PaystackOverride(inner, create_refund=duplicate))
        quote_id = await owed(stack)
        await stack.run_jobs()
        assert (await refund_of(stack, quote_id)).state == "sent"
        assert len(await sim_refunds(stack)) == 1
