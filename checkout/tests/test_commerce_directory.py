# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `directory` provider and the registry: what it lists, how it finds offers, that Mama Put is the menu
of food/menu.py, and that a second provider is one more entry and no new tool."""

import pytest

from checkout.commerce.directory import DirectoryProvider
from checkout.commerce.model import MAX_QUANTITY, Merchant
from checkout.commerce.registry import Providers
from checkout.errors import DomainError
from checkout.food.menu import DELIVERY_AREAS, DELIVERY_FEE_KOBO, MENU
from tests.commerce_support import GROCER, MAMA, PHARMACY, WATER, add_merchant, refusal


@pytest.fixture
def directory(stack) -> DirectoryProvider:
    return DirectoryProvider(stack.db, stack.clock)


class TestWhatItLists:
    async def test_four_simulated_merchants_live_ones_first(self, directory):
        listed = await directory.merchants()
        assert [m.id for m in listed] == [GROCER, PHARMACY, MAMA, WATER]
        assert [m.status for m in listed] == ["live", "live", "live", "beta"]
        assert {m.provider for m in listed} == {"directory"}
        assert all("(simulated)" in m.name for m in listed)

    async def test_a_category_narrows_the_list(self, directory):
        assert [m.id for m in await directory.merchants("health")] == [PHARMACY]
        assert await directory.merchants("tv") == []

    async def test_a_provider_lists_and_finds_only_its_own_merchants(self, stack, directory):
        await add_merchant(stack, "vtpass-shop", provider="vtpass")
        assert "vtpass-shop" not in [m.id for m in await directory.merchants()]
        assert await directory.merchant("vtpass-shop") is None

    async def test_a_merchant_is_found_by_id_and_a_missing_one_is_none(self, directory):
        found = await directory.merchant(MAMA)
        assert found is not None and found.fee_kobo == 120_000 and found.fee_label == "Delivery"
        assert (found.min_kobo, found.max_kobo) == (100_000, 3_000_000)
        assert await directory.merchant("dstv") is None

    async def test_a_merchant_says_what_the_buyer_must_give(self, directory):
        water = await directory.merchant(WATER)
        assert water.checks_account and [(f.name, f.kind) for f in water.fields] == [
            ("customer_number", "digits")
        ]
        mama = await directory.merchant(MAMA)
        assert [f.name for f in mama.fields] == ["area", "note"] and not mama.fields[1].required

    async def test_a_merchant_is_quotable_only_when_live_or_beta_and_needing_no_link(self, stack, directory):
        await add_merchant(stack, "soon", status="coming_soon")
        await add_merchant(stack, "linked", requires_link=1)
        quotable = {m.id: m.quotable for m in await directory.merchants()}
        assert quotable["soon"] is False and quotable["linked"] is False
        assert quotable[MAMA] is True and quotable[WATER] is True


class TestOffers:
    async def test_all_of_a_merchants_offers_come_in_its_own_order(self, directory):
        offers = await directory.offers(await directory.merchant(MAMA))
        assert [o.id for o in offers][:3] == ["jollof-chicken", "fried-rice-dodo", "egusi-pounded-yam"]
        assert len(offers) == 11

    async def test_words_must_all_be_found_in_the_name_description_or_tags(self, directory):
        mama = await directory.merchant(MAMA)
        assert [o.id for o in await directory.offers(mama, "rice")] == ["jollof-chicken", "fried-rice-dodo"]
        assert [o.id for o in await directory.offers(mama, "spicy soup")] == [
            "egusi-pounded-yam",
            "amala-ewedu",
            "catfish-pepper-soup",
        ]
        assert await directory.offers(mama, "pizza") == []

    async def test_a_query_is_words_and_never_a_pattern(self, directory):
        mama = await directory.merchant(MAMA)
        assert await directory.offers(mama, "%") == await directory.offers(mama)
        assert await directory.offers(mama, "r_ce") == await directory.offers(mama, "r ce")

    async def test_option_groups_and_price_kinds_are_read(self, directory):
        sanitiser = (await directory.offers(await directory.merchant(PHARMACY), "sanitiser"))[0]
        (group,) = sanitiser.option_groups
        assert (group.id, group.least, group.most) == ("size", 1, 1)
        assert [(c.id, c.delta_kobo) for c in group.choices] == [("100ml", 0), ("250ml", 110_000)]
        kinds = {o.id: o.price_kind for o in await directory.offers(await directory.merchant(WATER))}
        assert kinds == {"water-bill": "open", "prepaid-credit": "range", "reconnection": "fixed"}


class TestMamaPutIsTheMenu:
    """The menu of food/menu.py is listed in the directory, the same for as long as both exist."""

    async def test_every_menu_item_is_an_offer_with_its_id_name_price_and_availability(self, directory):
        offers = await directory.offers(await directory.merchant(MAMA))
        assert [(o.id, o.name, o.price_kobo, o.available) for o in offers] == [
            (item.id, item.name, item.price_kobo, item.available) for item in MENU
        ]

    async def test_the_descriptions_and_words_to_search_by_are_the_menus(self, directory):
        offers = {o.id: o for o in await directory.offers(await directory.merchant(MAMA))}
        for item in MENU:
            assert offers[item.id].description == item.description
            assert set(offers[item.id].tags.split()) == set(item.tags)

    async def test_the_restaurant_serves_the_same_areas_for_the_same_delivery_fee(self, directory):
        mama = await directory.merchant(MAMA)
        assert mama.fee_kobo == DELIVERY_FEE_KOBO
        assert mama.fields[0].options == DELIVERY_AREAS

    async def test_an_offer_never_allows_more_than_the_most_of_one_item(self, directory):
        offers = await directory.offers(await directory.merchant(MAMA))
        assert {o.max_quantity for o in offers} == {MAX_QUANTITY}


class TestAccountChecksOfTheSimulatedMerchants:
    async def test_an_account_the_merchant_knows_gives_its_holder_and_what_is_due(self, directory):
        water = await directory.merchant(WATER)
        found = await directory.check(water, {"customer_number": "10012345"})
        assert (found.holder_name, found.due_kobo) == ("ADEBAYO OLUWASEUN FOLA", 1_250_000)

    async def test_an_unknown_account_is_refused(self, directory):
        water = await directory.merchant(WATER)
        assert await refusal(directory.check(water, {"customer_number": "99999999"})) == "ACCOUNT_NOT_FOUND"

    async def test_a_merchant_that_does_not_check_is_not_asked_to(self, directory):
        mama = await directory.merchant(MAMA)
        assert await refusal(directory.check(mama, {"area": "Yaba"})) == "CHECK_NOT_NEEDED"


class StubProvider:
    """A provider of its own: one merchant, and no way to fulfil an order."""

    name = "stub"

    def __init__(self) -> None:
        self.merchant_row = Merchant(
            "stub-shop", "stub", "Stub Shop", "shop", "live", False, "b", 1, 2, "Fee", 0, False, ()
        )

    async def merchants(self, category=None):
        return [self.merchant_row] if category in (None, "shop") else []

    async def merchant(self, merchant_id):
        return self.merchant_row if merchant_id == "stub-shop" else None


class TestTheRegistry:
    async def test_it_lists_every_providers_merchants_and_routes_a_merchant_to_its_own(self, directory):
        stub = StubProvider()
        providers = Providers(directory, stub)
        assert [m.id for m in await providers.merchants()][-1] == "stub-shop"
        assert [m.id for m in await providers.merchants("shop")] == ["stub-shop"]
        merchant = await providers.merchant("stub-shop")
        assert providers.of(merchant) is stub and providers.of(await providers.merchant(MAMA)) is directory

    async def test_a_merchant_that_no_provider_lists_is_refused(self, directory):
        assert await refusal(Providers(directory).merchant("dstv")) == "MERCHANT_NOT_FOUND"

    async def test_two_providers_may_not_share_a_name(self, stack, directory):
        with pytest.raises(ValueError):
            Providers(directory, DirectoryProvider(stack.db, stack.clock))

    async def test_a_quote_names_its_provider_and_an_unknown_one_is_refused(self, directory):
        assert Providers(directory).named("directory") is directory
        with pytest.raises(DomainError) as refused:
            Providers(directory).named("vtpass")
        assert refused.value.code == "PROVIDER_UNAVAILABLE"

    async def test_the_first_provider_to_list_an_id_owns_it(self, stack, directory):
        await add_merchant(stack, "stub-shop")
        providers = Providers(directory, StubProvider())
        assert (await providers.merchant("stub-shop")).provider == "directory"
