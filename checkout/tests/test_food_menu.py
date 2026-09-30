# SPDX-License-Identifier: AGPL-3.0-or-later
"""The menu, ported from the TypeScript demo's menu.test.ts."""

import pytest

from checkout.errors import DomainError
from checkout.food.menu import (
    DELIVERY_FEE_KOBO,
    MENU,
    assert_delivery_area,
    describe_basket,
    price_basket,
    search_menu,
)


def code_of(work) -> str:
    try:
        work()
    except DomainError as error:
        return error.code
    return "none"


class TestTheMenu:
    def test_is_a_small_lagos_menu_with_prices_in_kobo_and_unique_ids(self):
        assert 8 <= len(MENU) <= 12
        assert len({m.id for m in MENU}) == len(MENU)
        assert all(m.price_kobo % 100 == 0 for m in MENU)

    def test_searches_names_descriptions_and_tags_and_by_price(self):
        assert [m.id for m in search_menu("jollof", None)] == ["jollof-chicken"]
        assert {"egusi-pounded-yam", "catfish-pepper-soup"} <= {m.id for m in search_menu("spicy soup", None)}
        assert sorted(m.id for m in search_menu("drink", 1000)) == ["water", "zobo"]
        assert len(search_menu(None, None)) == len(MENU)
        assert search_menu("pizza", None) == []


class TestSoldOut:
    def test_lists_a_sold_out_item_but_never_prices_it(self):
        sold_out = [m for m in MENU if not m.available]
        assert [m.id for m in sold_out] == ["amala-ewedu"]
        assert [m.id for m in search_menu("amala", None)] == ["amala-ewedu"]
        assert code_of(lambda: price_basket([("amala-ewedu", 1)])) == "ITEM_UNAVAILABLE"
        assert code_of(lambda: price_basket([("zobo", 1), ("amala-ewedu", 1)])) == "ITEM_UNAVAILABLE"


class TestPriceBasket:
    def test_prices_from_the_menu_and_adds_the_delivery_fee(self):
        basket = price_basket([("jollof-chicken", 2), ("zobo", 1)])
        assert basket.subtotal_kobo == 2 * 450_000 + 80_000
        assert basket.total_kobo == basket.subtotal_kobo + DELIVERY_FEE_KOBO
        assert [line.name for line in basket.lines] == ["Jollof rice with fried chicken", "Zobo, 500ml"]

    def test_merges_a_repeated_item(self):
        basket = price_basket([("zobo", 2), ("zobo", 3)])
        assert [(line.item_id, line.quantity) for line in basket.lines] == [("zobo", 5)]

    @pytest.mark.parametrize(
        "requested",
        [
            [],
            [("pizza", 1)],
            [("zobo", 0)],
            [("zobo", 1.5)],
            [("zobo", 11)],
            [("zobo", 6), ("zobo", 5)],
            [("zobo", True)],
            [(f"item-{i}", 1) for i in range(13)],
        ],
        ids=[
            "empty",
            "unknown",
            "zero",
            "fraction",
            "eleven",
            "eleven merged",
            "a boolean",
            "thirteen lines",
        ],
    )
    def test_refuses_a_basket_that_is_not_one_the_menu_can_price(self, requested):
        assert code_of(lambda: price_basket(requested)) == "INVALID_INPUT"

    def test_describes_the_basket_line_by_line(self):
        assert describe_basket(price_basket([("water", 2)])) == (
            "2 x Bottled water, 75cl: ₦600\nDelivery: ₦1,200\nTotal: ₦1,800"
        )


class TestDeliveryAreas:
    def test_matches_an_area_whatever_its_case_and_refuses_others_naming_the_ones_served(self):
        assert assert_delivery_area(" yaba ") == "Yaba"
        assert assert_delivery_area("lekki phase 1") == "Lekki Phase 1"
        with pytest.raises(DomainError, match="delivers to: Yaba"):
            assert_delivery_area("Abuja")
