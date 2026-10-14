# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bills under races, as D1 without transactions makes them possible: two requests that make the same quote
make one; one quote is approved once however it is asked; an approval racing the quote's expiry either wins or
leaves the wallet as it was; VTpass is ordered from once; and a callback racing a requery reverses and refunds
once."""

import asyncio

from checkout.commerce.model import Outcome
from checkout.commerce.vtpass_provider import VtpassProvider
from checkout.flows import merchant_leg
from checkout.flows.reversal import reverse_if_confirmed
from checkout.http import handle
from checkout.owner import acting_for
from tests.bills_support import (
    PENDING,
    RENEWAL_KOBO,
    check_id,
    electricity_quote,
    pay_from_wallet,
    renewal,
    renewal_quote,
    state_of,
)
from tests.commerce_support import approval, as_account, fund, stored
from tests.connector_support import quote_of
from tests.support import ALICE
from tests.wallet_support import entries, journal_of


class TestTwoRequestsForTheSameQuote:
    async def test_the_same_key_made_together_makes_one_quote(self, stack):
        arguments = renewal(await check_id(stack, "dstv", "1212121212"))
        results = await asyncio.gather(*[as_account(stack, "create_quote", **arguments) for _ in range(8)])
        assert len({quote_of(r)["id"] for r in results}) == 1 and await stack.count("quotes") == 1


class TestOneApproval:
    async def test_two_wallet_approvals_together_take_the_money_once_and_order_once(self, stack):
        await fund(stack, 5_000_000, ALICE)
        made = await renewal_quote(stack)
        both = await asyncio.gather(
            *[as_account(stack, "approve_quote", **approval(made, funding="wallet")) for _ in range(2)]
        )
        assert all("isError" not in r for r in both)
        assert len(await entries(stack, "spend")) == 1 and await stack.count("sim_vtpass") == 1
        assert await journal_of(stack).balance(ALICE) == 5_000_000 - RENEWAL_KOBO

    async def test_a_wallet_and_a_checkout_approval_together_leave_one_way_of_paying(self, stack):
        await fund(stack, 5_000_000, ALICE)
        made = await electricity_quote(stack)
        await asyncio.gather(
            as_account(stack, "approve_quote", **approval(made, funding="wallet")),
            as_account(stack, "approve_quote", **approval(made)),
        )
        paid_by_wallet = (await stored(stack, quote_of(made)["id"]))["progress"].get("funding") == "wallet"
        spends = await entries(stack, "spend")
        if paid_by_wallet:
            assert len(spends) == 1 and await stack.count("sim_vtpass") == 1
        else:
            assert len(await entries(stack, "release")) == len(spends)
            assert await journal_of(stack).balance(ALICE) == 5_000_000

    async def test_an_approval_that_loses_to_the_expiry_gives_the_wallets_hold_back(self, stack, monkeypatch):
        await fund(stack, 5_000_000, ALICE)
        made = await renewal_quote(stack)
        wallet = stack.app.contexts["merchants"].wallet
        hold = wallet.hold

        async def hold_then_time_runs_out(owner, quote_row):
            held = await hold(owner, quote_row)
            stack.clock.advance(601)
            return held

        monkeypatch.setattr(wallet, "hold", hold_then_time_runs_out)
        result = await as_account(stack, "approve_quote", **approval(made, funding="wallet"))
        assert result["isError"] is True and "QUOTE_EXPIRED" in result["content"][0]["text"]
        assert len(await entries(stack, "release")) == 1 and await stack.count("sim_vtpass") == 0
        assert await journal_of(stack).balance(ALICE) == 5_000_000
        assert await state_of(stack, quote_of(made)["id"]) == "expired"

    async def test_an_expired_quote_is_never_ordered_by_a_late_approval(self, stack):
        made = await electricity_quote(stack)
        stack.clock.advance(601)
        result = await as_account(stack, "approve_quote", **approval(made))
        assert "QUOTE_EXPIRED" in result["content"][0]["text"] and await stack.count("sim_vtpass") == 0


class TestOneOrder:
    async def test_vtpass_is_ordered_from_once_however_many_check_together(self, stack, monkeypatch):
        placed = []
        real = VtpassProvider.fulfil

        async def counting(self, quote):
            placed.append(quote.id)
            return await real(self, quote)

        monkeypatch.setattr(VtpassProvider, "fulfil", counting)
        await fund(stack, 5_000_000, ALICE)
        made = await electricity_quote(stack)
        quote_id = quote_of(made)["id"]
        await as_account(stack, "approve_quote", **approval(made, funding="wallet"))
        views = await asyncio.gather(
            *[as_account(stack, "verify_quote", quote_id=quote_id) for _ in range(20)]
        )
        assert placed == [quote_id] and await stack.count("sim_vtpass") == 1
        assert {quote_of(v)["phase"] for v in views} == {"succeeded"}

    async def test_the_request_id_is_chosen_once_however_many_verify_together(self, stack):
        await fund(stack, 5_000_000, ALICE)
        made = await renewal_quote(stack)
        await asyncio.gather(
            *[as_account(stack, "approve_quote", **approval(made, funding="wallet")) for _ in range(6)]
        )
        started = [line for line in stack.audit_lines if '"fulfilment.started"' in line]
        assert len(started) == 1

    async def test_a_pending_order_is_asked_about_by_one_caller_at_a_time(self, stack, monkeypatch):
        asked = []
        real = VtpassProvider.status

        async def counting(self, quote):
            asked.append(quote.id)
            return await real(self, quote)

        monkeypatch.setattr(VtpassProvider, "status", counting)
        await fund(stack, 5_000_000, ALICE)
        made = await renewal_quote(stack, PENDING)
        quote_id = quote_of(made)["id"]
        await as_account(stack, "approve_quote", **approval(made, funding="wallet"))
        with acting_for(ALICE):
            assert await stack.ledger.acquire_step(quote_id, merchant_leg.STEP_STALE_MS)
        held = quote_of(await as_account(stack, "verify_quote", quote_id=quote_id))
        assert held["phase"] == "processing" and asked == []
        stack.clock.advance(merchant_leg.STEP_STALE_MS / 1000 + 1)
        await as_account(stack, "verify_quote", quote_id=quote_id)
        assert asked == [quote_id]

    async def test_a_delivered_answer_arriving_after_a_refusal_changes_nothing_and_gives_no_token(
        self, stack
    ):
        await fund(stack, 5_000_000, ALICE)
        made = await electricity_quote(stack, "100000000000")
        quote_id = quote_of(made)["id"]
        await as_account(stack, "approve_quote", **approval(made, funding="wallet"))
        ctx = stack.app.contexts["merchants"]
        with acting_for(ALICE):
            owed = await ctx.ledger.get(quote_id)
            late = await merchant_leg._record(
                ctx, owed, owed.progress["fulfilment"], Outcome("delivered", "LATE", (("Token", "1234"),))
            )
        assert late.state == owed.state and "receipt" not in late.progress["fulfilment"]


class TestACallbackRacingARequery:
    async def test_a_reversal_reported_and_requeried_together_refunds_once(self, stack):
        done = await pay_from_wallet(stack, await electricity_quote(stack))
        request_id = (await stored(stack, done["id"]))["progress"]["fulfilment"]["requestId"]
        await handle(stack.app, "POST", f"/test/vtpass-reverse/{request_id}", {}, b"")
        ctx = stack.app.contexts["merchants"]
        racing = [reverse_if_confirmed(ctx, done["id"], "merchants") for _ in range(6)]
        with acting_for(ALICE):
            await asyncio.gather(stack.run_jobs(), *racing)
        assert await state_of(stack, done["id"]) == "reversed" and len(await entries(stack, "refund")) == 1
        assert await journal_of(stack).balance(ALICE) == 10_000_000
        assert len([line for line in stack.audit_lines if '"fulfilment.reversed"' in line]) == 1

    async def test_a_callback_and_a_verify_on_a_pending_bill_settle_it_once(self, stack):
        done = await pay_from_wallet(stack, await renewal_quote(stack, PENDING))
        stack.clock.advance(21)
        await asyncio.gather(*[as_account(stack, "verify_quote", quote_id=done["id"]) for _ in range(5)])
        assert await state_of(stack, done["id"]) == "settled" and await stack.count("sim_vtpass") == 1
        assert len([line for line in stack.audit_lines if '"fulfilment.delivered"' in line]) == 1
