# SPDX-License-Identifier: AGPL-3.0-or-later
"""The menu card's tools through JSON-RPC: search_menu tells the model little and the card everything, and
the app-only order tool prices on the server and makes the one quote a menu card may make."""

import json
import re

import pytest

from tests.connector_support import MENU_URI, listed, quote_of, text_of, visibility

CARD_ID = "0123456789abcdef0123456789abcdef"


def order(**over):
    return {
        "card_id": CARD_ID,
        "items": [{"item_id": "beef-suya", "quantity": 2}, {"item_id": "zobo", "quantity": 1}],
        "delivery_area": "Surulere",
        **over,
    }


class TestSearchMenu:
    async def test_tells_the_model_one_line_and_leaves_the_items_to_the_card(self, stack):
        found = await stack.call("food-order", "search_menu")
        text = text_of(found)
        assert "\n" not in text and "11 items match" in text
        assert "do not list the items or prices" in text
        assert "Beef suya" not in text and "₦" not in text and "beef-suya" not in text
        assert len(found["content"]) == 1

    async def test_gives_the_card_the_menu_with_prices_in_kobo_availability_and_areas(self, stack):
        data = (await stack.call("food-order", "search_menu", query="suya"))["structuredContent"]
        assert data["merchant"] == "Mama Put Yaba (simulated)"
        assert data["items"] == [
            {
                "item_id": "beef-suya",
                "name": "Beef suya, 200g",
                "note": "Grilled beef with onions, tomato and yaji",
                "price_kobo": 350_000,
                "available": True,
                "category": "mains",
                "art": "skewer",
            }
        ]
        assert data["areas"][:2] == ["Yaba", "Surulere"] and data["delivery_fee_kobo"] == 120_000
        assert len(data["card_id"]) == 32

    async def test_lists_a_sold_out_item_as_unavailable(self, stack):
        items = (await stack.call("food-order", "search_menu"))["structuredContent"]["items"]
        assert {i["item_id"]: i["available"] for i in items}["amala-ewedu"] is False
        assert sum(not i["available"] for i in items) == 1

    async def test_gives_each_search_its_own_card_id(self, stack):
        first = (await stack.call("food-order", "search_menu"))["structuredContent"]["card_id"]
        second = (await stack.call("food-order", "search_menu"))["structuredContent"]["card_id"]
        assert first != second

    async def test_shows_no_card_when_nothing_matches(self, stack):
        none = await stack.call("food-order", "search_menu", query="pizza")
        assert text_of(none) == "No menu items match." and "structuredContent" not in none

    async def test_is_offered_to_the_model_and_names_the_menu_view(self, stack):
        tool = (await listed(stack, "food-order"))["search_menu"]
        assert tool["_meta"]["ui"] == {"resourceUri": MENU_URI, "visibility": ["model"]}
        assert tool["_meta"]["ui/resourceUri"] == MENU_URI

    async def test_keeps_the_typescript_arguments(self, stack):
        schema = (await listed(stack, "food-order"))["search_menu"]["inputSchema"]
        assert sorted(schema["properties"]) == ["max_price_naira", "query"]
        assert schema["additionalProperties"] is False and "required" not in schema


class TestTheMenuView:
    async def test_is_listed_as_an_mcp_app_resource(self, stack):
        listing = (await stack.mcp("food-order", "resources/list"))["result"]["resources"]
        view = next(r for r in listing if r["uri"] == MENU_URI)
        assert view["mimeType"] == "text/html;profile=mcp-app" and view["_meta"] == {
            "ui": {"prefersBorder": False}
        }

    async def test_serves_a_page_that_loads_nothing_from_the_network(self, stack):
        read = (await stack.mcp("food-order", "resources/read", {"uri": MENU_URI}))["result"]["contents"][0]
        page = read["text"]
        assert read["mimeType"] == "text/html;profile=mcp-app" and "<html" in page
        assert not re.search(r"""(src|href)=["']https?:""", page.replace("http://www.w3.org/2000/svg", ""))
        assert "order_from_menu" in page and "ui/request-display-mode" in page

    async def test_declares_no_image_origin_for_a_merchant_without_photos(self, stack):
        read = (await stack.mcp("food-order", "resources/read", {"uri": MENU_URI}))["result"]["contents"][0]
        assert "csp" not in read["_meta"]["ui"]


class TestOrderFromMenu:
    async def test_is_for_cards_only(self, stack):
        tools = await listed(stack, "food-order")
        assert visibility(tools["order_from_menu"]) == ["app"]
        assert tools["order_from_menu"]["_meta"]["ui"]["resourceUri"] == MENU_URI
        assert "Not for the model" in tools["order_from_menu"]["description"]

    async def test_takes_ids_quantities_and_an_area_and_nothing_else(self, stack):
        schema = (await listed(stack, "food-order"))["order_from_menu"]["inputSchema"]
        assert sorted(schema["properties"]) == ["card_id", "delivery_area", "items"]
        assert sorted(schema["properties"]["items"]["items"]["properties"]) == ["item_id", "quantity"]

    @pytest.mark.parametrize(
        "over",
        [
            {"total_kobo": 1},
            {"items": [{"item_id": "zobo", "quantity": 1, "price": 1}]},
            {"items": [{"item_id": "zobo", "quantity": 1, "unit_kobo": 1}]},
        ],
        ids=["a total", "a price on a line", "a unit price on a line"],
    )
    async def test_refuses_a_price_from_the_card(self, stack, over):
        result = await stack.call("food-order", "order_from_menu", **order(**over))
        assert result["isError"] is True and await stack.count("quotes") == 0

    async def test_prices_on_the_server_and_opens_the_approval_card(self, stack):
        made = await stack.call("food-order", "order_from_menu", **order())
        quote = quote_of(made)
        assert (
            quote["amount"]["display"] == "₦9,000"
            or quote["amount"]["kobo"] == 2 * 350_000 + 80_000 + 120_000
        )
        assert quote["phase"] == "awaiting_approval" and quote["details"]["area"] == "Surulere"
        assert made["_meta"]["ui"] == {"resourceUri": "ui://food-order/card.html"}
        assert len(made["_meta"]["approvalToken"]) == 64

    async def test_keeps_the_approval_token_out_of_the_text_and_the_structure(self, stack):
        made = await stack.call("food-order", "order_from_menu", **order())
        token = made["_meta"]["approvalToken"]
        assert token not in text_of(made) and token not in json.dumps(made["structuredContent"])

    async def test_can_be_approved_with_its_own_token(self, stack):
        made = await stack.call("food-order", "order_from_menu", **order())
        quote = quote_of(made)
        approved = await stack.call(
            "food-order", "approve_quote", quote_id=quote["id"],
            approval_token=made["_meta"]["approvalToken"], displayed_amount_kobo=quote["amount"]["kobo"],
        )  # fmt: skip
        assert quote_of(approved)["phase"] == "awaiting_checkout"

    async def test_makes_one_quote_for_a_card_however_often_it_is_pressed(self, stack):
        first = await stack.call("food-order", "order_from_menu", **order())
        again = await stack.call("food-order", "order_from_menu", **order())
        assert quote_of(first)["id"] == quote_of(again)["id"] and await stack.count("quotes") == 1

    async def test_refuses_a_different_basket_from_a_card_that_already_ordered(self, stack):
        await stack.call("food-order", "order_from_menu", **order())
        other = await stack.call(
            "food-order", "order_from_menu", **order(items=[{"item_id": "water", "quantity": 1}])
        )
        assert text_of(other).startswith("IDEMPOTENCY_CONFLICT") and await stack.count("quotes") == 1

    async def test_lets_two_menu_cards_each_make_a_quote(self, stack):
        first = await stack.call("food-order", "order_from_menu", **order())
        second = await stack.call("food-order", "order_from_menu", **order(card_id="f" * 32))
        assert quote_of(first)["id"] != quote_of(second)["id"]

    async def test_refuses_a_sold_out_item(self, stack):
        result = await stack.call(
            "food-order", "order_from_menu", **order(items=[{"item_id": "amala-ewedu", "quantity": 1}])
        )
        assert text_of(result).startswith("ITEM_UNAVAILABLE") and await stack.count("quotes") == 0

    @pytest.mark.parametrize(
        ("over", "code"),
        [
            ({"items": [{"item_id": "pizza", "quantity": 1}]}, "INVALID_INPUT"),
            ({"items": [{"item_id": "zobo", "quantity": 0}]}, "Invalid arguments"),
            ({"items": [{"item_id": "zobo", "quantity": 11}]}, "Invalid arguments"),
            ({"items": [{"item_id": "zobo", "quantity": 1.5}]}, "Invalid arguments"),
            ({"items": []}, "Invalid arguments"),
            ({"delivery_area": "Abuja"}, "Invalid arguments"),
            ({"card_id": "short"}, "Invalid arguments"),
            ({"card_id": "G" * 32}, "Invalid arguments"),
        ],
    )
    async def test_refuses_input_the_menu_cannot_price(self, stack, over, code):
        result = await stack.call("food-order", "order_from_menu", **order(**over))
        assert result["isError"] is True and code in text_of(result) and await stack.count("quotes") == 0

    async def test_refuses_a_sold_out_item_in_a_basket_check_and_a_model_quote(self, stack):
        items = [{"item_id": "amala-ewedu", "quantity": 1}]
        basket = await stack.call("food-order", "build_basket", items=items)
        quote = await stack.call(
            "food-order", "create_food_quote", items=items, delivery_area="Yaba",
            idempotency_key="sold-out-0001",
        )  # fmt: skip
        assert text_of(basket).startswith("ITEM_UNAVAILABLE") and text_of(quote).startswith(
            "ITEM_UNAVAILABLE"
        )
