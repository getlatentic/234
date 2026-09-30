# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `food-order` connector: order from an invented Lagos restaurant. The merchant is simulated, not
Chowdeck; payment still goes through Paystack, and delivery follows a clock."""

from typing import Annotated, Literal

from pydantic import Field

from ..flows.context import Context, QuoteIssued
from ..flows.food import FoodFlow
from ..food.menu import (
    DELIVERY_AREAS,
    DELIVERY_FEE_KOBO,
    RESTAURANT,
    describe_basket,
    price_basket,
    search_menu,
)
from ..food.view import CARD_ID_HEX, menu_line, menu_view, new_card_id, view_meta
from ..mcp.registry import Connector, ToolResult, UiResource
from ..money import format_naira
from .kit import CardConnector, CardReader, IdempotencyKey, Strict, plain_result

NAME = "food-order"
MENU_URI = f"ui://{NAME}/menu.html"

DeliveryArea = Literal[*DELIVERY_AREAS]


class BasketItem(Strict):
    item_id: Annotated[str, Field(min_length=1, max_length=40, description="An item_id from search_menu.")]
    quantity: Annotated[int, Field(ge=1, le=10, description="How many, 1 to 10.")]


Items = Annotated[
    list[BasketItem],
    Field(
        min_length=1,
        max_length=12,
        description="The items and how many of each. Prices are the menu's; you cannot set them.",
    ),
]


class SearchMenu(Strict):
    query: Annotated[str | None, Field(max_length=60)] = None
    max_price_naira: Annotated[int | None, Field(gt=0)] = None


class BuildBasket(Strict):
    items: Items


class OrderFromMenu(Strict):
    card_id: Annotated[
        str,
        Field(
            pattern=rf"^[0-9a-f]{{{CARD_ID_HEX}}}$",
            description="The card_id of the menu card that is asking.",
        ),
    ]
    items: Items
    delivery_area: Annotated[DeliveryArea, Field(description="Where to deliver.")]


class CreateFoodQuote(Strict):
    items: Items
    delivery_area: Annotated[DeliveryArea, Field(description="Where to deliver.")]
    note: Annotated[
        str | None, Field(max_length=120, description="A note for the rider, such as a landmark.")
    ] = None
    total_as_user_said: Annotated[
        str | None,
        Field(
            max_length=80,
            description="The total the person expects, in their words, if they gave one. "
            "It is checked against the server's total.",
        ),
    ] = None
    idempotency_key: IdempotencyKey


def _pairs(items: list[BasketItem]) -> list[tuple[str, int]]:
    return [(i.item_id, i.quantity) for i in items]


def build_connector(ctx: Context, card_html: CardReader, menu_html: CardReader) -> Connector:
    flow = FoodFlow(ctx)
    kit = CardConnector(NAME, "Food order (simulated merchant, not Chowdeck)", ctx, flow, card_html)

    async def search(args: SearchMenu) -> ToolResult:
        found = search_menu(args.query, args.max_price_naira)
        if not found:
            return {"content": [{"type": "text", "text": "No menu items match."}]}
        return plain_result(menu_line(found), menu_view(found, new_card_id()))

    async def basket(args: BuildBasket) -> ToolResult:
        priced = price_basket(_pairs(args.items))
        return plain_result(
            f"{describe_basket(priced)}\nThis is only a price check. Call create_food_quote to get the "
            f"approval card.",
            {"total": format_naira(priced.total_kobo), "total_kobo": priced.total_kobo},
        )

    async def create(args: CreateFoodQuote) -> QuoteIssued:
        return await flow.create_quote(
            items=_pairs(args.items),
            delivery_area=args.delivery_area,
            note=args.note,
            total_as_user_said=args.total_as_user_said,
            idempotency_key=args.idempotency_key,
        )

    async def order(args: OrderFromMenu) -> QuoteIssued:
        return await flow.create_quote(
            items=_pairs(args.items),
            delivery_area=args.delivery_area,
            note=None,
            total_as_user_said=None,
            idempotency_key=f"menu-{args.card_id}",
        )

    menu_view_resource = UiResource(
        MENU_URI,
        "Menu card",
        "Shows the menu with a search, a cart and a Review order action.",
        menu_html,
        view_meta(),
    )
    tools = (
        kit.view_tool(
            "search_menu",
            "Search the menu",
            f"Shows {RESTAURANT}'s menu (simulated merchant, not Chowdeck) to the person on a card, "
            'optionally filtered by words like "rice", "spicy" or "drink" and by a top price in naira. '
            "The person picks items on the card; you are told only how many match.",
            SearchMenu,
            search,
            MENU_URI,
        ),
        kit.plain_tool(
            "build_basket",
            "Build a basket",
            "Prices a basket from the menu, with delivery, and returns the total. It creates no order and "
            "shows no card; use it to confirm the total with the person.",
            BuildBasket,
            basket,
        ),
        kit.quote_tool(
            "create_food_quote",
            "Create food order quote",
            "Creates a server-side quote for the basket and shows the person an approval card with the "
            "items, delivery fee and total. The server prices it; nothing is ordered or charged until the "
            "person presses Approve and pays on Paystack's checkout. The merchant is simulated, not "
            "Chowdeck.",
            CreateFoodQuote,
            create,
        ),
    )
    order_tool = kit.card_quote_tool(
        "order_from_menu",
        "Called by the menu card when the person presses Review order: it prices the items on the "
        "server and makes the quote. Not for the model.",
        OrderFromMenu,
        order,
        MENU_URI,
    )
    return kit.build(
        f"Order food from {RESTAURANT}, an invented Lagos restaurant. This is a simulated merchant: it is "
        f"not "
        "Chowdeck and the menu, prices and delivery are made up",
        tools,
        (
            f"Delivery costs {format_naira(DELIVERY_FEE_KOBO)}. Areas served: {', '.join(DELIVERY_AREAS)}.",
            "Search the menu to show it on a card: the person picks items there and orders from the card, "
            "and the server prices them. Never list the menu yourself. You pass items and quantities "
            "only, never a price.",
            "Delivery progress is simulated by a clock: accepted, preparing, on the way, delivered.",
        ),
        views=(menu_view_resource,),
        app_tools=(order_tool,),
    )
