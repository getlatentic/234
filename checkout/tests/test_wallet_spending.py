# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paying airtime from the wallet (wallet/spending.py, flows/wallet_leg.py): hold, claim, release, and the
refund when VTpass fails after approval. Simulated Paystack and VTpass, the real ledger and journal."""

import asyncio

import pytest

from checkout.ledger import ClaimTerms
from checkout.owner import DEFAULT_OWNER
from checkout.wallet.spending import HOLD_LIVE, WALLET_PAID
from tests.airtime_support import approve, code_of, paid, quote_input, vtpass_orders
from tests.wallet_support import entries, fund, journal_of


async def _quote(stack, **over):
    return await stack.airtime.create_airtime_quote(**quote_input(**over))


async def _from_wallet(stack, issued, amount=50_000):
    return await stack.airtime.approve(
        issued.quote["id"], issued.approval_token, amount, True, funding="wallet"
    )


def _spending(stack):
    return stack.app.contexts["airtime"].wallet


async def _balance(stack) -> int:
    return await journal_of(stack).balance(DEFAULT_OWNER)


class TestPayingFromTheWallet:
    async def test_holds_claims_and_delivers_without_a_checkout(self, stack):
        await fund(stack, 200_000)
        view = await _from_wallet(stack, await _quote(stack))
        assert (view["phase"], view["receipt"]["title"]) == ("succeeded", "Airtime delivered")
        assert await _balance(stack) == 150_000
        assert [e["kind"] for e in await entries(stack)] == ["fund", "spend"]
        assert await stack.count("sim_transactions") == 0
        assert await vtpass_orders(stack) == 1
        assert '"funding": "wallet"' in "\n".join(stack.audit_lines)

    async def test_a_wallet_that_does_not_cover_the_quote_takes_nothing_and_leaves_it_open(self, stack):
        await fund(stack, 49_900)
        issued = await _quote(stack)
        assert await code_of(_from_wallet(stack, issued)) == "WALLET_SHORT"
        assert (await stack.ledger.get(issued.quote["id"])).state == "open"
        assert await entries(stack, "spend") == []

    async def test_a_frozen_wallet_pays_nothing(self, stack):
        await fund(stack, 200_000)
        await journal_of(stack).set_frozen(DEFAULT_OWNER, True)
        issued = await _quote(stack)
        assert await code_of(_from_wallet(stack, issued)) == "WALLET_FROZEN"
        assert (await stack.ledger.get(issued.quote["id"])).state == "open"

    async def test_the_card_and_the_read_back_are_checked_before_anything_is_held(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack)
        flow = stack.airtime
        wrong_token = flow.approve(issued.quote["id"], "0" * 64, 50_000, True, funding="wallet")
        assert await code_of(wrong_token) == "APPROVAL_DENIED"
        assert await code_of(_from_wallet(stack, issued, amount=60_000)) == "AMOUNT_MISMATCH"
        no_readback = flow.approve(issued.quote["id"], issued.approval_token, 50_000, False, funding="wallet")
        assert await code_of(no_readback) == "READBACK_REQUIRED"
        assert await entries(stack, "spend") == []

    async def test_is_refused_where_no_wallet_is_offered(self, stack):
        stack.override("airtime", wallet=None)
        assert await code_of(_from_wallet(stack, await _quote(stack))) == "WALLET_UNAVAILABLE"


class TestALostClaimGivesTheHoldBack:
    async def test_an_expired_quote(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack)
        stack.clock.advance(601)
        assert await code_of(_from_wallet(stack, issued)) == "QUOTE_EXPIRED"
        assert [e["kind"] for e in await entries(stack)] == ["fund", "spend", "release"]
        assert await _balance(stack) == 200_000

    async def test_a_quote_over_the_daily_limit(self, stack):
        await fund(stack, 20_000_000)
        made = [await _quote(stack, amount_kobo=5_000_000, amount_as_user_said="₦50,000") for _ in range(3)]
        for issued in made[:2]:
            await _from_wallet(stack, issued, amount=5_000_000)
        assert await code_of(_from_wallet(stack, made[2], amount=5_000_000)) == "LIMIT_DAILY"
        assert len(await entries(stack, "release")) == 1
        assert await _balance(stack) == 10_000_000

    async def test_a_quote_already_approved_for_the_checkout(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack)
        checkout = await approve(stack.airtime, issued)
        view = await _from_wallet(stack, issued)
        assert view["checkoutUrl"] == checkout["checkoutUrl"]
        assert len(await entries(stack, "release")) == 1
        assert await _balance(stack) == 200_000


class TestOneQuoteIsPaidOnce:
    async def test_approving_again_from_the_wallet_spends_once_and_releases_nothing(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack)
        await _from_wallet(stack, issued)
        assert (await _from_wallet(stack, issued))["phase"] == "succeeded"
        assert [e["kind"] for e in await entries(stack)] == ["fund", "spend"]
        assert await _balance(stack) == 150_000

    async def test_racing_wallet_approvals_of_one_quote_spend_once(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack)
        await asyncio.gather(*[_from_wallet(stack, issued) for _ in range(8)], return_exceptions=True)
        assert [e["kind"] for e in await entries(stack)] == ["fund", "spend"]
        assert await _balance(stack) == 150_000
        assert await vtpass_orders(stack) == 1

    async def test_racing_wallet_approvals_of_many_quotes_never_overspend_the_wallet(self, stack):
        await fund(stack, 120_000)
        made = [await _quote(stack) for _ in range(6)]
        await asyncio.gather(*[_from_wallet(stack, issued) for issued in made], return_exceptions=True)
        assert len(await entries(stack, "spend")) == 2
        assert await _balance(stack) == 20_000

    async def test_a_checkout_approval_while_a_wallet_paid_order_is_pending_starts_no_checkout(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack, phone="201000000000")
        assert (await _from_wallet(stack, issued))["phase"] == "processing"
        view = await approve(stack.airtime, issued)
        assert (view["phase"], view.get("checkoutUrl")) == ("processing", None)
        assert await stack.count("sim_transactions") == 0

    async def test_a_wallet_paid_quote_keeps_its_hold_when_a_release_comes_late(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack)
        await _from_wallet(stack, issued)
        assert not await _spending(stack).release(DEFAULT_OWNER, issued.quote["id"])
        assert await _balance(stack) == 150_000

    async def test_a_released_hold_cannot_pay_for_the_quote(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack)
        quote = await stack.ledger.get(issued.quote["id"])
        await _spending(stack).hold(DEFAULT_OWNER, quote)
        assert await _spending(stack).release(DEFAULT_OWNER, quote.id)
        assert await code_of(_from_wallet(stack, issued)) == "WALLET_RELEASED"
        assert (await stack.ledger.get(quote.id)).state == "open"
        assert await _balance(stack) == 200_000

    async def test_the_claim_itself_refuses_a_released_hold(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack)
        quote = await stack.ledger.get(issued.quote["id"])
        await _spending(stack).hold(DEFAULT_OWNER, quote)
        await _spending(stack).release(DEFAULT_OWNER, quote.id)
        claim = stack.ledger.claim_approval(quote.id, "airtime", ClaimTerms(WALLET_PAID, HOLD_LIVE))
        assert await code_of(claim) == "APPROVAL_IN_PROGRESS"
        assert (await stack.ledger.get(quote.id)).state == "open"

    async def test_the_claim_itself_refuses_a_quote_whose_hold_is_on_another_quote(self, stack):
        await fund(stack, 200_000)
        held, other = await _quote(stack), await _quote(stack, amount_kobo=40_000, amount_as_user_said="₦400")
        await _spending(stack).hold(DEFAULT_OWNER, await stack.ledger.get(held.quote["id"]))
        claim = stack.ledger.claim_approval(other.quote["id"], "airtime", ClaimTerms(WALLET_PAID, HOLD_LIVE))
        assert await code_of(claim) == "APPROVAL_IN_PROGRESS"
        assert (await stack.ledger.get(other.quote["id"])).state == "open"

    async def test_the_claim_itself_refuses_a_hold_for_less_than_the_quote(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack)
        await journal_of(stack).debit(DEFAULT_OWNER, "spend", 100, issued.quote["id"])
        claim = stack.ledger.claim_approval(issued.quote["id"], "airtime", ClaimTerms(WALLET_PAID, HOLD_LIVE))
        assert await code_of(claim) == "APPROVAL_IN_PROGRESS"


class TestRefundWhenVtpassFails:
    async def test_the_money_goes_back_to_the_wallet_and_the_quote_ends_failed(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack, phone="100000000000")
        view = await _from_wallet(stack, issued)
        assert view["phase"] == "failed"
        assert "₦500 is back in the wallet" in view["message"]
        assert [e["kind"] for e in await entries(stack)] == ["fund", "spend", "refund"]
        assert await _balance(stack) == 200_000
        assert (await stack.ledger.budget()).spent_today_kobo == 0
        assert "wallet.refunded" in "\n".join(stack.audit_lines)

    async def test_checking_again_refunds_nothing_more(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack, phone="100000000000")
        await _from_wallet(stack, issued)
        assert (await stack.airtime.verify(issued.quote["id"]))["phase"] == "failed"
        assert len(await entries(stack, "refund")) == 1

    async def test_a_refund_interrupted_before_it_was_written_is_finished_by_the_next_check(
        self, stack, monkeypatch
    ):
        await fund(stack, 200_000)
        issued = await _quote(stack, phone="100000000000")

        async def interrupted(owner, quote_id):
            raise RuntimeError("the Worker stopped here")

        monkeypatch.setattr(_spending(stack), "refund", interrupted)
        with pytest.raises(RuntimeError):
            await _from_wallet(stack, issued)
        assert (await stack.ledger.get(issued.quote["id"])).state == "refund_due"
        monkeypatch.undo()
        assert (await stack.airtime.verify(issued.quote["id"]))["phase"] == "failed"
        assert await _balance(stack) == 200_000

    async def test_a_quote_paid_at_the_checkout_gets_no_wallet_refund(self, stack):
        await fund(stack, 200_000)
        quote_id = await paid(stack, phone="100000000000")
        view = await stack.airtime.verify(quote_id)
        assert view["phase"] == "attention"
        assert not await _spending(stack).refund(DEFAULT_OWNER, quote_id)
        assert await entries(stack, "refund") == []

    async def test_a_quote_paid_at_the_checkout_after_its_wallet_hold_was_given_back_gets_no_refund(
        self, stack
    ):
        await fund(stack, 200_000)
        issued = await _quote(stack, phone="100000000000")
        checkout = await approve(stack.airtime, issued)
        await _from_wallet(stack, issued)
        await stack.complete_checkout(checkout["checkoutUrl"], "success")
        assert (await stack.airtime.verify(issued.quote["id"]))["phase"] == "attention"
        assert not await _spending(stack).refund(DEFAULT_OWNER, issued.quote["id"])
        assert [e["kind"] for e in await entries(stack)] == ["fund", "spend", "release"]
        assert await _balance(stack) == 200_000

    async def test_a_delivered_quote_gets_no_refund(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack)
        await _from_wallet(stack, issued)
        assert not await _spending(stack).refund(DEFAULT_OWNER, issued.quote["id"])
        assert await _balance(stack) == 150_000
