# SPDX-License-Identifier: AGPL-3.0-or-later
"""Orders under races: what D1 without transactions makes possible, and the guards that hold. Two requests
that make the same quote make one; one quote is approved once whoever asks and however; an approval racing the
quote's expiry either wins or leaves the wallet as it was; the merchant is ordered from once."""

import asyncio

from checkout.commerce.directory import DirectoryProvider
from tests.commerce_support import approval, as_account, fund, meal, stored
from tests.connector_support import quote_of
from tests.support import ALICE
from tests.wallet_support import entries, journal_of


async def made(stack):
    return await as_account(stack, "create_quote", **meal())


class TestTwoRequestsForTheSameQuote:
    async def test_the_same_key_made_together_makes_one_quote(self, stack):
        arguments = meal()
        results = await asyncio.gather(*[as_account(stack, "create_quote", **arguments) for _ in range(10)])
        assert len({quote_of(r)["id"] for r in results}) == 1
        assert len({r["_meta"]["approvalToken"] for r in results}) == 1
        assert await stack.count("quotes") == 1

    async def test_different_keys_made_together_make_a_quote_each(self, stack):
        results = await asyncio.gather(*[as_account(stack, "create_quote", **meal()) for _ in range(5)])
        assert len({quote_of(r)["id"] for r in results}) == 5

    async def test_the_same_key_for_different_orders_made_together_makes_one_and_refuses_the_rest(
        self, stack
    ):
        zobo = meal(lines=[{"offer_id": "zobo"}], idempotency_key="race-key-00001")
        jollof = meal(lines=[{"offer_id": "jollof-chicken"}], idempotency_key="race-key-00001")
        results = await asyncio.gather(
            as_account(stack, "create_quote", **zobo), as_account(stack, "create_quote", **jollof)
        )
        assert sorted("isError" in r for r in results) == [False, True]
        assert await stack.count("quotes") == 1


class TestOneApproval:
    async def test_two_wallet_approvals_together_take_the_money_once(self, stack):
        await fund(stack, 5_000_000, ALICE)
        quote = await made(stack)
        both = await asyncio.gather(
            *[as_account(stack, "approve_quote", **approval(quote, funding="wallet")) for _ in range(2)]
        )
        assert all("isError" not in r for r in both)
        assert len(await entries(stack, "spend")) == 1
        assert await journal_of(stack).balance(ALICE) == 5_000_000 - 1_100_000

    async def test_a_wallet_and_a_checkout_approval_together_leave_one_way_of_paying(self, stack):
        await fund(stack, 5_000_000, ALICE)
        quote = await made(stack)
        wallet, checkout = await asyncio.gather(
            as_account(stack, "approve_quote", **approval(quote, funding="wallet")),
            as_account(stack, "approve_quote", **approval(quote)),
        )
        paid_by_wallet = (await stored(stack, quote_of(quote)["id"]))["progress"].get("funding") == "wallet"
        spends = await entries(stack, "spend")
        if paid_by_wallet:
            assert len(spends) == 1 and quote_of(wallet)["phase"] == "succeeded"
            assert quote_of(checkout)["checkoutUrl"] is None
        else:
            assert len(await entries(stack, "release")) == len(spends)
            assert await journal_of(stack).balance(ALICE) == 5_000_000

    async def test_an_approval_that_loses_to_the_expiry_gives_the_wallets_hold_back(self, stack, monkeypatch):
        await fund(stack, 5_000_000, ALICE)
        quote = await made(stack)
        wallet = stack.app.contexts["merchants"].wallet
        hold = wallet.hold

        async def hold_then_time_runs_out(owner, quote_row):
            held = await hold(owner, quote_row)
            stack.clock.advance(601)
            return held

        monkeypatch.setattr(wallet, "hold", hold_then_time_runs_out)
        result = await as_account(stack, "approve_quote", **approval(quote, funding="wallet"))
        assert result["isError"] is True and "QUOTE_EXPIRED" in result["content"][0]["text"]
        assert len(await entries(stack, "release")) == 1
        assert await journal_of(stack).balance(ALICE) == 5_000_000
        assert (await stored(stack, quote_of(quote)["id"]))["state"] == "expired"

    async def test_an_expired_quote_is_never_claimed_by_a_late_checkout_approval(self, stack):
        quote = await made(stack)
        stack.clock.advance(601)
        result = await as_account(stack, "approve_quote", **approval(quote))
        assert "QUOTE_EXPIRED" in result["content"][0]["text"]
        assert (await stored(stack, quote_of(quote)["id"]))["state"] == "expired"


class TestOneOrder:
    async def test_the_merchant_is_ordered_from_once_however_many_check_together(self, stack, monkeypatch):
        placed = []
        real = DirectoryProvider.fulfil

        async def counting(self, quote):
            placed.append(quote.id)
            return await real(self, quote)

        monkeypatch.setattr(DirectoryProvider, "fulfil", counting)
        await fund(stack, 5_000_000, ALICE)
        quote = await made(stack)
        quote_id = quote_of(quote)["id"]
        await as_account(stack, "approve_quote", **approval(quote, funding="wallet"))
        views = await asyncio.gather(
            *[as_account(stack, "verify_quote", quote_id=quote_id) for _ in range(20)]
        )
        assert placed == [quote_id] and await stack.count("sim_merchant_order") == 1
        assert {quote_of(v)["phase"] for v in views} == {"succeeded"}

    async def test_the_request_id_is_chosen_once_however_many_verify_together(self, stack):
        await fund(stack, 5_000_000, ALICE)
        quote = await made(stack)
        quote_id = quote_of(quote)["id"]
        await asyncio.gather(
            *[as_account(stack, "approve_quote", **approval(quote, funding="wallet")) for _ in range(6)]
        )
        started = [line for line in stack.audit_lines if '"fulfilment.started"' in line]
        assert len(started) == 1
        assert (await stored(stack, quote_id))["progress"]["fulfilment"]["requestId"] == f"mrq-{quote_id}"

    async def test_a_settled_order_checked_again_is_neither_refunded_nor_ordered_again(self, stack):
        await fund(stack, 5_000_000, ALICE)
        quote = await made(stack)
        quote_id = quote_of(quote)["id"]
        await as_account(stack, "approve_quote", **approval(quote, funding="wallet"))
        assert (await stored(stack, quote_id))["state"] == "settled"
        again = await as_account(stack, "verify_quote", quote_id=quote_id)
        assert quote_of(again)["phase"] == "succeeded" and len(await entries(stack, "refund")) == 0
        assert await stack.count("sim_merchant_order") == 1
