# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prices and totals are the provider's alone, in integer kobo (docs/commerce.md, rule 1): the model's
lines carry an offer, a count and option ids, and the only money it may name is an amount for a single open
or range offer, within that offer's limits."""

import pytest

from checkout.commerce.directory import DirectoryProvider
from checkout.commerce.model import MAX_LINES, AccountCheck, Basket, BasketLine
from tests.commerce_support import GROCER, MAMA, PHARMACY, WATER, add_merchant, add_offer, refusal


@pytest.fixture
def directory(stack) -> DirectoryProvider:
    return DirectoryProvider(stack.db, stack.clock)


def basket(*lines, amount=None, **fields) -> Basket:
    made = tuple(BasketLine(*line) if isinstance(line, tuple) else line for line in lines)
    return Basket(made, amount, fields)


async def price(directory, merchant_id, *lines, amount=None, check=None, **fields):
    merchant = await directory.merchant(merchant_id)
    return await directory.price(merchant, basket(*lines, amount=amount, **fields), check)


class TestAFixedPriceIsTheOffers:
    async def test_totals_are_the_offers_prices_times_counts_plus_the_merchants_fee(self, directory):
        totals = await price(directory, MAMA, ("jollof-chicken", 2), ("zobo", 1), area="Yaba")
        assert [(line.offer_id, line.quantity, line.unit_kobo) for line in totals.lines] == [
            ("jollof-chicken", 2, 450_000),
            ("zobo", 1, 80_000),
        ]
        assert totals.subtotal_kobo == 980_000
        assert [(f.label, f.kobo) for f in totals.fees] == [("Delivery", 120_000)]
        assert totals.total_kobo == 1_100_000

    async def test_the_same_offer_twice_is_one_line(self, directory):
        totals = await price(directory, MAMA, ("zobo", 1), ("zobo", 2), area="Yaba")
        assert [(line.quantity, line.total_kobo) for line in totals.lines] == [(3, 240_000)]

    async def test_a_merchant_without_a_fee_has_no_fee_line(self, stack, directory):
        await add_merchant(stack)
        totals = await price(directory, "test-shop", ("item", 2))
        assert totals.fees == () and totals.total_kobo == 400_000

    async def test_an_amount_is_not_taken_for_an_offer_with_a_price(self, directory):
        assert (
            await refusal(price(directory, MAMA, ("zobo", 1), amount=1, area="Yaba")) == "AMOUNT_NOT_ACCEPTED"
        )

    async def test_an_option_adds_its_own_price(self, directory):
        totals = await price(directory, PHARMACY, BasketLine("hand-sanitiser", 1, ("250ml",)), area="Yaba")
        assert totals.lines[0].unit_kobo == 90_000 + 110_000 and totals.lines[0].options == ("250ml",)


class TestEveryLineIsCheckedAgainstTheOffers:
    async def test_an_offer_the_merchant_does_not_have_is_refused(self, directory):
        assert await refusal(price(directory, MAMA, ("rice-5kg", 1), area="Yaba")) == "OFFER_NOT_FOUND"

    async def test_an_offer_of_another_merchant_is_not_found_under_this_one(self, directory):
        assert await refusal(price(directory, GROCER, ("zobo", 1), area="Yaba")) == "OFFER_NOT_FOUND"

    async def test_a_sold_out_offer_is_refused(self, directory):
        assert await refusal(price(directory, MAMA, ("amala-ewedu", 1), area="Yaba")) == "ITEM_UNAVAILABLE"

    @pytest.mark.parametrize("quantity", [0, -1, 11, True, 1.5, "2"])
    async def test_a_count_is_a_whole_number_from_one_to_ten(self, directory, quantity):
        assert await refusal(price(directory, MAMA, ("zobo", quantity), area="Yaba")) == "INVALID_INPUT"

    async def test_an_offer_has_its_own_most(self, directory):
        assert await refusal(price(directory, GROCER, ("eggs-crate", 5), area="Yaba")) == "INVALID_INPUT"
        assert (await price(directory, GROCER, ("eggs-crate", 4), area="Yaba")).subtotal_kobo == 1_800_000

    async def test_a_basket_has_one_to_twelve_different_items(self, stack, directory):
        assert await refusal(price(directory, MAMA, area="Yaba")) == "INVALID_INPUT"
        await add_merchant(stack)
        for n in range(MAX_LINES):
            await add_offer(stack, "test-shop", f"more-{n}", price_kobo=10_000)
        lines = [(f"more-{n}", 1) for n in range(MAX_LINES)]
        assert (await price(directory, "test-shop", *lines)).subtotal_kobo == 120_000
        assert await refusal(price(directory, "test-shop", *lines, ("item", 1))) == "INVALID_INPUT"

    async def test_options_must_be_the_offers_and_complete(self, directory):
        for options in ((), ("500ml",), ("100ml", "250ml"), ("100ml", "100ml")):
            line = BasketLine("hand-sanitiser", 1, options)
            assert await refusal(price(directory, PHARMACY, line, area="Yaba")) == "OPTION_INVALID"

    async def test_options_are_refused_for_an_offer_that_has_none(self, directory):
        line = BasketLine("zobo", 1, ("large",))
        assert await refusal(price(directory, MAMA, line, area="Yaba")) == "OPTION_INVALID"


class TestTheAmountOfAnOpenOrRangeOffer:
    async def test_an_open_offer_takes_the_persons_amount_within_the_merchants_limits(self, directory):
        totals = await price(
            directory, WATER, ("water-credit", 1), amount=500_000, check=await check_of(directory)
        )
        assert totals.total_kobo == 500_000 and totals.lines[0].unit_kobo == 500_000

    async def test_an_amount_below_or_above_the_limits_is_refused_and_nothing_is_priced(self, directory):
        check = await check_of(directory)
        for amount in (49_999, 5_000_001, 1):
            assert (
                await refusal(price(directory, WATER, ("water-credit", 1), amount=amount, check=check))
                == "AMOUNT_OUT_OF_LIMITS"
            )

    async def test_a_range_offer_has_its_own_limits_inside_the_merchants(self, directory):
        check = await check_of(directory)
        ok = await price(directory, WATER, ("tanker-booking", 1), amount=100_000, check=check)
        assert ok.total_kobo == 100_000
        for amount in (99_999, 2_000_001):
            assert (
                await refusal(price(directory, WATER, ("tanker-booking", 1), amount=amount, check=check))
                == "AMOUNT_OUT_OF_LIMITS"
            )

    async def test_an_open_offer_without_an_amount_is_refused(self, directory):
        check = await check_of(directory)
        assert await refusal(price(directory, WATER, ("water-credit", 1), check=check)) == "AMOUNT_REQUIRED"

    async def test_an_open_offer_stands_alone_and_is_paid_once(self, directory):
        check = await check_of(directory)
        both = price(
            directory, WATER, ("water-credit", 1), ("meter-reconnection", 1), amount=100_000, check=check
        )
        assert await refusal(both) == "INVALID_INPUT"
        twice = price(directory, WATER, ("water-credit", 2), amount=100_000, check=check)
        assert await refusal(twice) == "INVALID_INPUT"


class TestTheMerchantsLimitsOnAnOrder:
    async def test_an_order_below_the_least_is_refused_with_its_fees_counted(self, stack, directory):
        await add_merchant(stack, "tiny", min_kobo=100_000, fee_kobo=10_000)
        await add_offer(stack, "tiny", "pin", price_kobo=60_000)
        assert await refusal(price(directory, "tiny", ("pin", 1))) == "ORDER_OUT_OF_LIMITS"
        assert (await price(directory, "tiny", ("pin", 2))).total_kobo == 130_000

    async def test_an_order_above_the_most_is_refused(self, directory):
        assert (
            await refusal(price(directory, MAMA, ("catfish-pepper-soup", 6), area="Yaba"))
            == "ORDER_OUT_OF_LIMITS"
        )


class TestAnAccountCheck:
    async def test_a_merchant_that_checks_needs_one_and_one_that_does_not_takes_none(self, directory):
        assert (
            await refusal(price(directory, WATER, ("water-credit", 1), amount=100_000))
            == "ACCOUNT_CHECK_REQUIRED"
        )
        check = await check_of(directory)
        assert (
            await refusal(price(directory, MAMA, ("zobo", 1), check=check, area="Yaba"))
            == "ACCOUNT_CHECK_REQUIRED"
        )

    async def test_the_holder_in_the_totals_is_the_checks(self, directory):
        totals = await price(
            directory, WATER, ("water-credit", 1), amount=100_000, check=await check_of(directory)
        )
        assert totals.holder_name == "ADEBAYO OLUWASEUN FOLA" and totals.check_id == "ck-test"


async def check_of(directory):
    return AccountCheck("ck-test", WATER, "ADEBAYO OLUWASEUN FOLA", 1_250_000, {}, 0, 10**15)


def test_the_basket_a_model_sends_has_no_field_for_a_price():
    assert [f for f in BasketLine.__dataclass_fields__] == ["offer_id", "quantity", "options"]
