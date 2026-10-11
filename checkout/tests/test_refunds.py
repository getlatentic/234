# SPDX-License-Identifier: AGPL-3.0-or-later
"""A quote paid at the checkout that ends owing its payer (refunds/): the refund is sent through Paystack's
Refund API and followed to its outcome, processed, failed or needing attention, and the card says where the
money is. Paystack's refund event is only a hint, verified by asking Paystack. Simulated Paystack, whose
refunds the test routes move on."""

import base64
import hashlib
import json

from checkout.flows.reversal import reverse_if_confirmed
from checkout.http import handle
from checkout.owner import DEFAULT_OWNER
from checkout.transport import Reply
from tests.refund_support import (
    audited,
    delivered,
    owed,
    paystack_moves,
    refund_hook,
    refund_of,
    refunded,
    sim_refunds,
    sweep,
)
from tests.support import ScriptedTransport


async def _view(stack, quote_id):
    return await stack.airtime.status(quote_id)


class TestSent:
    async def test_an_owed_refund_is_sent_for_the_whole_amount_and_waits_on_paystack(self, stack):
        quote_id = await refunded(stack)
        (sent,) = await sim_refunds(stack)
        assert (sent["amount_kobo"], sent["status"], sent["currency"]) == (50_000, "pending", "NGN")
        refund = await refund_of(stack, quote_id)
        assert (refund.state, refund.refund_status, refund.refund_id) == ("sent", "pending", sent["id"])
        assert refund.sending_since is None and refund.decided_at is None
        assert (await stack.ledger.get(quote_id)).state == "refund_due"

    async def test_the_card_says_it_is_refunding(self, stack):
        quote_id = await refunded(stack)
        view = await _view(stack, quote_id)
        assert view["phase"] == "attention"
        assert view["refund"] == {"title": "Refunding ₦500", "state": "sent"}
        assert view["message"].endswith("₦500 is being refunded to the card or account that paid.")

    async def test_paystack_processing_it_leaves_it_undecided(self, stack):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, "processing")
        refund = await refund_of(stack, quote_id)
        assert (refund.state, refund.refund_status) == ("sent", "processing")


class TestProcessed:
    async def test_ends_the_quote_refunded_and_it_no_longer_counts_against_the_day(self, stack):
        quote_id = await refunded(stack)
        assert (await stack.ledger.budget()).spent_today_kobo == 50_000
        answer = await paystack_moves(stack, quote_id, "processed")
        assert answer.status == 200
        refund = await refund_of(stack, quote_id)
        assert (refund.state, refund.decided_at is not None) == ("processed", True)
        assert (await stack.ledger.get(quote_id)).state == "refunded"
        assert (await stack.ledger.budget()).spent_today_kobo == 0
        assert audited(stack, "refund.processed") == 1

    async def test_the_card_says_refunded(self, stack):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, "processed")
        view = await _view(stack, quote_id)
        assert view["phase"] == "refunded"
        assert view["refund"] == {"title": "Refunded ₦500", "state": "processed"}
        assert view["message"] == (
            "VTpass did not deliver: TRANSACTION FAILED. ₦500 was refunded to the card or account that paid."
        )

    async def test_the_refund_is_told_as_the_quotes_ending(self, stack):
        quote_id = await refunded(stack)
        transport = ScriptedTransport(lambda sent: Reply(200, "{}"))
        object.__setattr__(stack.app.background.delivery, "_transport", transport)
        await stack.db.execute(
            "INSERT INTO event_subscriptions (id, owner, connector, name, quote_id, arguments, url, secret,"
            " expires_at, created_at) VALUES ('sub-1', ?, 'airtime', 'quote.finished', ?, '{}', ?, ?, ?, 0)",
            DEFAULT_OWNER,
            quote_id,
            "https://agent.example/events",
            "whsec_" + base64.b64encode(b"k" * 32).decode(),
            stack.clock.now() + 3_600_000,
        )
        await paystack_moves(stack, quote_id, "processed")
        sent = [call.body["data"] for call in transport.calls if call.body.get("name") == "quote.finished"]
        assert [(data["quote_id"], data["state"]) for data in sent] == [(quote_id, "refunded")]


class TestFailed:
    async def test_is_decided_audited_and_the_quote_stays_owed(self, stack):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, "failed")
        refund = await refund_of(stack, quote_id)
        assert (refund.state, refund.refund_status) == ("failed", "failed")
        assert (await stack.ledger.get(quote_id)).state == "refund_due"
        assert audited(stack, "refund.failed") == 1

    async def test_the_card_says_it_failed_and_234_follows_up(self, stack):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, "failed")
        view = await _view(stack, quote_id)
        assert view["phase"] == "attention" and view["refund"]["title"] == "Refund failed"
        assert view["message"].endswith("The refund failed. 234 will follow up.")

    async def test_a_failed_refund_is_never_sent_again(self, stack):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, "failed")
        await sweep(stack, 3600)
        assert len(await sim_refunds(stack)) == 1
        assert (await refund_of(stack, quote_id)).state == "failed"

    async def test_failed_refunds_are_found_by_one_query(self, stack):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, "failed")
        rows = await stack.rows("SELECT quote_id FROM quote_refund WHERE state IN ('failed', 'refused')")
        assert rows == [{"quote_id": quote_id}]


class TestNeedsAttention:
    async def test_stays_undecided_and_the_card_says_it_is_delayed(self, stack):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, "needs-attention")
        refund = await refund_of(stack, quote_id)
        assert (refund.state, refund.decided_at) == ("needs_attention", None)
        assert audited(stack, "refund.needs_attention") == 1
        view = await _view(stack, quote_id)
        assert view["refund"]["title"] == "Refund delayed"
        assert view["message"].endswith(
            "Paystack needs the payer's bank account to refund ₦500. 234 will follow up."
        )

    async def test_then_processed_found_by_the_minute_refunds_it(self, stack):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, "needs-attention")
        await stack.db.execute("UPDATE sim_refunds SET status = 'processed'")
        await sweep(stack)
        assert (await refund_of(stack, quote_id)).state == "processed"
        assert (await stack.ledger.get(quote_id)).state == "refunded"


class TestTheEventIsAHint:
    async def test_an_unsigned_event_is_refused_and_moves_nothing(self, stack):
        quote_id = await refunded(stack)
        await stack.db.execute("UPDATE sim_refunds SET status = 'processed'")
        answer = await refund_hook(stack, quote_id, "processed", signed=False)
        await stack.run_jobs()
        assert answer.status == 401
        assert (await refund_of(stack, quote_id)).state == "sent"

    async def test_a_signed_event_paystack_does_not_confirm_moves_nothing(self, stack):
        quote_id = await refunded(stack)
        answer = await refund_hook(stack, quote_id, "processed")
        await stack.run_jobs()
        assert answer.status == 200
        refund = await refund_of(stack, quote_id)
        assert (refund.state, refund.refund_status) == ("sent", "pending")
        assert (await stack.ledger.get(quote_id)).state == "refund_due"

    async def test_an_event_for_a_refund_already_decided_asks_nothing(self, stack):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, "processed")
        await refund_hook(stack, quote_id, "failed")
        assert stack.jobs.held == []
        assert (await refund_of(stack, quote_id)).state == "processed"


class TestWhoStartsIt:
    async def test_ending_owed_asks_for_the_refund_at_once(self, stack):
        await owed(stack)
        asked = [job for job in stack.jobs.held if job["kind"] == "refund"]
        assert [job["source"] for job in asked] == ["ended"]

    async def test_the_minute_opens_an_owed_refund_that_was_never_started(self, stack):
        quote_id = await owed(stack)
        stack.jobs.held.clear()
        await sweep(stack)
        assert (await refund_of(stack, quote_id)).state == "sent"
        assert len(await sim_refunds(stack)) == 1

    async def test_a_payment_landing_after_the_checkout_was_given_up_on_is_refunded(self, stack):
        flow = stack.payments
        issued = await flow.create_quote(
            amount_kobo=500_000,
            amount_as_user_said="five thousand naira",
            description="Lunch",
            merchant="Demo Kitchen",
            merchant_ref=None,
            idempotency_key="late-payment-0001",
        )
        view = await flow.approve(issued.quote["id"], issued.approval_token, 500_000)
        await flow.verify(issued.quote["id"], checkout_closed=True)
        await stack.complete_checkout(view["checkoutUrl"], "success")
        await flow.verify(issued.quote["id"])
        assert any(job["kind"] == "refund" and job["source"] == "ended" for job in stack.jobs.held)
        await stack.run_jobs()
        (sent,) = await sim_refunds(stack)
        assert sent["amount_kobo"] == 500_000

    async def test_a_refund_is_followed_as_its_quotes_owner(self, stack):
        await refunded(stack)
        (line,) = [json.loads(line) for line in stack.audit_lines if '"refund.sent"' in line]
        assert line["owner"] == hashlib.sha256(DEFAULT_OWNER.encode()).hexdigest()[:12]

    async def test_the_minute_waits_before_opening_one(self, stack):
        await owed(stack)
        stack.jobs.held.clear()
        await stack.app.background.minute()
        assert stack.jobs.held == []


class TestAReversedOrderPaidAtTheCheckout:
    async def _reversed(self, stack) -> str:
        quote_id = await delivered(stack)
        request_id = (await stack.ledger.get(quote_id)).progress["fulfilment"]["requestId"]
        await handle(stack.app, "POST", f"/test/vtpass-reverse/{request_id}", {}, b"")
        await stack.run_jobs()
        return quote_id

    async def test_is_refunded_and_stays_reversed(self, stack):
        quote_id = await self._reversed(stack)
        assert (await refund_of(stack, quote_id)).state == "sent"
        await paystack_moves(stack, quote_id, "processed")
        assert (await refund_of(stack, quote_id)).state == "processed"
        assert (await stack.ledger.get(quote_id)).state == "reversed"
        view = await _view(stack, quote_id)
        assert (view["phase"], view["refund"]["title"]) == ("refunded", "Refunded ₦500")

    async def test_a_second_reversal_refunds_nothing_more(self, stack):
        quote_id = await self._reversed(stack)
        await reverse_if_confirmed(stack.app.contexts["airtime"], quote_id)
        await stack.run_jobs()
        assert len(await sim_refunds(stack)) == 1
