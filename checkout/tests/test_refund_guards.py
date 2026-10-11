# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a refund may never do (refunds/, migrations/0019_quote_refund.sql): refund a quote that was never paid
at the checkout for exactly its amount, send a wallet-paid quote's money to Paystack, change its terms or a
decision, or end a quote refunded before Paystack processed its refund."""

import pytest

from checkout.owner import DEFAULT_OWNER
from checkout.paystack.api import PaystackError
from checkout.refunds.opening import RefundOpening
from tests.airtime_support import paid
from tests.refund_support import (
    UNDELIVERABLE,
    audited,
    owed,
    paystack_moves,
    paystack_of,
    reference_of,
    refund_of,
    refunded,
    sim_refunds,
    sweep,
    with_paystack,
)
from tests.support import PaystackOverride
from tests.wallet_support import entries, fund


async def _owed_unpaid(stack, change: str) -> str:
    """An owed quote whose payment Paystack then holds otherwise: `change` is applied to it."""
    quote_id = await owed(stack)
    reference = await reference_of(stack, quote_id)
    await stack.db.execute(f"UPDATE sim_transactions SET {change} WHERE reference = ?", reference)
    await stack.run_jobs()
    return quote_id


class TestOnlyAPaymentOfExactlyTheAmountIsRefunded:
    async def test_a_payment_paystack_does_not_hold_as_a_success_is_refused(self, stack):
        quote_id = await _owed_unpaid(stack, "status = 'failed'")
        refund = await refund_of(stack, quote_id)
        assert (refund.state, refund.why) == ("refused", "Paystack reports the payment failed.")
        assert await sim_refunds(stack) == []
        assert audited(stack, "refund.refused") == 1

    async def test_a_payment_of_another_amount_is_refused(self, stack):
        quote_id = await _owed_unpaid(stack, "amount_kobo = 100")
        assert (await refund_of(stack, quote_id)).state == "refused"
        assert await sim_refunds(stack) == []

    async def test_the_card_says_a_refund_is_due_and_234_follows_up(self, stack):
        quote_id = await _owed_unpaid(stack, "status = 'failed'")
        view = await stack.airtime.status(quote_id)
        assert (view["phase"], view["refund"]["title"]) == ("attention", "Refund due")
        assert view["message"].endswith("A refund is due. 234 will follow up.")

    async def test_a_refused_refund_is_never_opened_again(self, stack):
        quote_id = await _owed_unpaid(stack, "status = 'failed'")
        await stack.db.execute("UPDATE sim_transactions SET status = 'success'")
        await sweep(stack, 3600)
        assert (await refund_of(stack, quote_id)).state == "refused"
        assert await sim_refunds(stack) == []

    async def test_a_payment_paystack_could_not_be_asked_about_is_asked_again_later(self, stack):
        async def unreachable(reference):
            raise PaystackError("Paystack could not be reached.", retryable=True)

        with_paystack(stack, PaystackOverride(paystack_of(stack), verify_transaction=unreachable))
        quote_id = await owed(stack)
        await stack.run_jobs()
        assert await refund_of(stack, quote_id) is None
        with_paystack(stack, paystack_of(stack))
        await sweep(stack)
        assert (await refund_of(stack, quote_id)).state == "sent"

    async def test_the_statement_that_opens_it_holds_the_amount(self, stack):
        quote_id = await owed(stack)
        quote = await stack.ledger.get(quote_id)
        opening = RefundOpening(stack.db, stack.clock, stack.app.contexts["airtime"].audit)
        wrong = type(quote)(**{**quote.__dict__, "amount_kobo": 100})
        assert await opening._insert(wrong, quote.progress["paystackReference"], 7, "sent", None) is False
        assert await refund_of(stack, quote_id) is None


class TestQuotesThatOweNoPaystackRefund:
    async def test_a_wallet_paid_order_is_refunded_to_the_wallet_and_never_to_paystack(self, stack):
        await fund(stack, 200_000)
        paystack = PaystackOverride(paystack_of(stack))
        with_paystack(stack, paystack)
        issued = await stack.airtime.create_airtime_quote(
            network="mtn",
            phone=UNDELIVERABLE,
            amount_kobo=50_000,
            amount_as_user_said="₦500",
            idempotency_key="wallet-refund-0001",
        )
        await stack.airtime.approve(issued.quote["id"], issued.approval_token, 50_000, True, funding="wallet")
        await stack.run_jobs()
        await sweep(stack, 3600)
        assert len(await entries(stack, "refund")) == 1
        assert await refund_of(stack, issued.quote["id"]) is None
        assert paystack.calls.get("create_refund", 0) == 0 and await sim_refunds(stack) == []

    async def test_the_statement_that_opens_it_refuses_a_wallet_paid_quote(self, stack):
        quote_id = await owed(stack)
        await stack.db.execute(
            'UPDATE quotes SET progress = json_patch(progress, \'{"funding": "wallet"}\') WHERE id = ?',
            quote_id,
        )
        await stack.run_jobs()
        assert await refund_of(stack, quote_id) is None and await sim_refunds(stack) == []

    async def test_the_statement_that_opens_it_holds_the_wallet_out(self, stack):
        quote_id = await owed(stack)
        quote = await stack.ledger.get(quote_id)
        await stack.db.execute(
            'UPDATE quotes SET progress = json_patch(progress, \'{"funding": "wallet"}\') WHERE id = ?',
            quote_id,
        )
        opening = RefundOpening(stack.db, stack.clock, stack.app.contexts["airtime"].audit)
        assert await opening._insert(quote, quote.progress["paystackReference"], 7, "sent", None) is False

    async def test_the_statement_that_opens_it_needs_the_quote_owing(self, stack):
        quote_id = await paid(stack)
        await stack.airtime.verify(quote_id)
        quote = await stack.ledger.get(quote_id)
        opening = RefundOpening(stack.db, stack.clock, stack.app.contexts["airtime"].audit)
        assert await opening._insert(quote, quote.progress["paystackReference"], 7, "sent", None) is False

    async def test_the_statement_that_opens_it_holds_the_payments_reference(self, stack):
        quote = await stack.ledger.get(await owed(stack))
        opening = RefundOpening(stack.db, stack.clock, stack.app.contexts["airtime"].audit)
        assert await opening._insert(quote, "qt-00000000000000000009-a1", 7, "sent", None) is False

    async def test_a_quote_marked_paid_from_the_wallet_is_never_asked_for(self, stack):
        quote_id = await owed(stack)
        stack.jobs.held.clear()
        await stack.db.execute(
            'UPDATE quotes SET progress = json_patch(progress, \'{"funding": "wallet"}\') WHERE id = ?',
            quote_id,
        )
        await stack.app.contexts["airtime"].refunds.ask(await stack.ledger.get(quote_id))
        assert stack.jobs.held == []

    async def test_a_quote_that_did_not_end_owing_is_never_refunded(self, stack):
        quote_id = await paid(stack)
        await stack.airtime.verify(quote_id)
        await sweep(stack, 3600)
        assert await refund_of(stack, quote_id) is None and await sim_refunds(stack) == []


class TestTheDatabaseKeepsIt:
    async def test_a_refund_keeps_its_quote_amount_and_transaction(self, stack):
        quote_id = await refunded(stack)
        for change in ("amount_kobo = 1", "transaction_reference = 'other'", "transaction_id = 1"):
            with pytest.raises(Exception, match="keeps its quote"):
                await stack.db.execute(f"UPDATE quote_refund SET {change} WHERE quote_id = ?", quote_id)

    async def test_a_refund_keeps_the_paystack_refund_it_was_given(self, stack):
        quote_id = await refunded(stack)
        with pytest.raises(Exception, match="keeps the Paystack refund"):
            await stack.db.execute("UPDATE quote_refund SET refund_id = 1 WHERE quote_id = ?", quote_id)

    async def test_a_decided_refund_stays_decided(self, stack):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, "failed")
        with pytest.raises(Exception, match="stays decided"):
            await stack.db.execute("UPDATE quote_refund SET state = 'sent' WHERE quote_id = ?", quote_id)

    async def test_a_quote_is_refunded_only_once_its_refund_is_processed(self, stack):
        quote_id = await refunded(stack)
        with pytest.raises(Exception, match="refunded only once"):
            await stack.db.execute("UPDATE quotes SET state = 'refunded' WHERE id = ?", quote_id)
        await paystack_moves(stack, quote_id, "processed")
        with pytest.raises(Exception, match="stays refunded"):
            await stack.db.execute("UPDATE quotes SET state = 'refund_due' WHERE id = ?", quote_id)

    async def test_only_an_owed_quote_becomes_refunded(self, stack):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, "processed")
        other = await paid(stack)
        await stack.airtime.verify(other)
        await stack.db.execute(
            "INSERT INTO quote_refund (quote_id, owner, amount_kobo, transaction_reference, transaction_id, "
            "state, created_at, decided_at) VALUES (?, ?, 50000, 'r', 1, 'processed', 0, 0)",
            other,
            DEFAULT_OWNER,
        )
        with pytest.raises(Exception, match="refunded only once"):
            await stack.db.execute("UPDATE quotes SET state = 'refunded' WHERE id = ?", other)
