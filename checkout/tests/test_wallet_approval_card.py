# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paying from the wallet on the airtime approval card, as the host calls it: the card is offered the
wallet only for an account whose balance covers the quote, `approve_quote` takes `funding` from the card
alone, and an approval without it is the checkout as it always was."""

from tests.connector_support import CONNECTORS, listed, text_of, visibility
from tests.support import ALICE, BOB
from tests.wallet_card_support import CARD_ID, airtime_quote, approve, call, ok, wallet


def journal(stack):
    return stack.app.funding.topups.journal


async def funded(stack, amount: int, owner: str = ALICE) -> None:
    await journal(stack).open(owner)
    assert await journal(stack).credit(owner, "fund", amount, f"top-up-{owner}") is not None


def offer_of(made: dict) -> dict | None:
    return made["structuredContent"]["quote"].get("wallet")


class TestTheOffer:
    async def test_an_account_whose_wallet_covers_the_quote_is_offered_it(self, stack):
        await funded(stack, 200_000)
        assert offer_of(await airtime_quote(stack)) == {"balanceKobo": 200_000, "balance": "₦2,000"}

    async def test_a_wallet_that_does_not_cover_the_quote_is_not_offered(self, stack):
        await funded(stack, 49_999)
        assert offer_of(await airtime_quote(stack)) is None

    async def test_exactly_the_amount_is_enough(self, stack):
        await funded(stack, 50_000)
        assert offer_of(await airtime_quote(stack))["balanceKobo"] == 50_000

    async def test_a_visitor_is_never_offered_a_wallet(self, stack):
        await funded(stack, 200_000, BOB)
        assert offer_of(await airtime_quote(stack, BOB, account=False)) is None

    async def test_the_offer_is_gone_once_the_quote_is_approved(self, stack):
        await funded(stack, 200_000)
        approved = ok(await approve(stack, await airtime_quote(stack)))
        assert "wallet" not in approved["structuredContent"]["quote"]


class TestPayingFromTheWallet:
    async def test_the_card_pays_from_the_wallet_and_the_balance_goes_down(self, stack):
        await funded(stack, 200_000)
        paid = ok(await approve(stack, await airtime_quote(stack), funding="wallet"))
        quote = paid["structuredContent"]["quote"]
        assert quote["phase"] == "succeeded" and quote["checkoutUrl"] is None
        assert await journal(stack).balance(ALICE) == 150_000
        view = ok(await wallet(stack, "wallet_view", card_id=CARD_ID))["structuredContent"]["wallet"]
        newest = view["entries"][0]
        assert (newest["label"], newest["amount"]) == ("Paid airtime", "-₦500")

    async def test_without_funding_the_approval_is_the_checkout_and_the_wallet_is_untouched(self, stack):
        await funded(stack, 200_000)
        approved = ok(await approve(stack, await airtime_quote(stack)))
        quote = approved["structuredContent"]["quote"]
        assert quote["phase"] == "awaiting_checkout" and "/sim/checkout/" in quote["checkoutUrl"]
        assert await journal(stack).balance(ALICE) == 200_000

    async def test_a_visitor_cannot_pay_from_a_wallet(self, stack):
        await funded(stack, 200_000, BOB)
        made = await airtime_quote(stack, BOB, account=False)
        refused = await approve(stack, made, BOB, account=False, funding="wallet")
        assert text_of(refused).startswith("WALLET_ACCOUNT_ONLY")
        assert await journal(stack).balance(BOB) == 200_000
        quote_id = made["structuredContent"]["quote"]["id"]
        assert await stack.rows("SELECT state FROM quotes WHERE id = ?", quote_id) == [{"state": "open"}]

    async def test_a_short_wallet_says_so_in_one_line_and_takes_nothing(self, stack):
        await funded(stack, 200_000)
        made = await airtime_quote(stack, amount_kobo=300_000, amount_as_user_said="₦3000")
        refused = await approve(stack, made, funding="wallet")
        assert text_of(refused).startswith("WALLET_SHORT") and "\n" not in text_of(refused)
        assert await journal(stack).balance(ALICE) == 200_000

    async def test_a_frozen_wallet_says_so_and_takes_nothing(self, stack):
        await funded(stack, 200_000)
        await journal(stack).set_frozen(ALICE, True)
        refused = await approve(stack, await airtime_quote(stack), funding="wallet")
        assert text_of(refused).startswith("WALLET_FROZEN")
        assert await journal(stack).balance(ALICE) == 200_000

    async def test_another_connector_does_not_pay_from_the_wallet(self, stack):
        await funded(stack, 2_000_000)
        made = await call(
            stack,
            "paystack-pay",
            "create_payment_quote",
            ALICE,
            True,
            amount_kobo=50_000,
            amount_as_user_said="₦500",
            description="Payment",
            merchant="Shop",
            idempotency_key="pay-wallet-0001",
        )
        refused = await approve(stack, made["result"], funding="wallet")
        assert refused["isError"] is True
        assert await journal(stack).balance(ALICE) == 2_000_000


class TestOnlyTheCardChoosesFunding:
    async def test_no_tool_the_model_sees_takes_a_funding(self, stack):
        for connector in [*CONNECTORS, "wallet"]:
            for name, tool in (await listed(stack, connector)).items():
                if "model" in (visibility(tool) or ["model"]):
                    assert "funding" not in tool["inputSchema"].get("properties", {}), name

    async def test_the_approval_tool_that_takes_it_is_for_cards_only(self, stack):
        approve_tool = (await listed(stack, "airtime"))["approve_quote"]
        assert visibility(approve_tool) == ["app"]
        assert approve_tool["inputSchema"]["properties"]["funding"]["enum"] == ["checkout", "wallet"]
        assert "funding" not in approve_tool["inputSchema"].get("required", [])
