# SPDX-License-Identifier: AGPL-3.0-or-later
"""The menu card's tools: what the model is told, what only a card may call, and one order for a card."""

from tools.mutations.model import (
    CONNECTOR_TOOLS,
    MENU_CARD,
    SRC,
    Mutation,
)

MUTATIONS: list[Mutation] = [
    Mutation(
        "a sold-out item is never priced into a basket",
        f"{SRC}/food/menu.py",
        "    if not entry.available:",
        "    if False:",
        MENU_CARD,
    ),
    Mutation(
        "the order tool is for cards only and is never offered to the model",
        f"{SRC}/connectors/kit.py",
        "return Tool(name, name, description, arguments, handler, view_uri, APP_ONLY, QUOTE_HINTS)",
        "return Tool(name, name, description, arguments, handler, view_uri, MODEL_ONLY, QUOTE_HINTS)",
        MENU_CARD + CONNECTOR_TOOLS,
    ),
    Mutation(
        "the menu search is the model's tool and names the menu view",
        f"{SRC}/connectors/kit.py",
        "return Tool(name, title, description, arguments, run, view_uri, MODEL_ONLY, QUOTE_HINTS)",
        "return Tool(name, title, description, arguments, run, view_uri, APP_ONLY, QUOTE_HINTS)",
        MENU_CARD + CONNECTOR_TOOLS,
    ),
    Mutation(
        "a menu card makes one quote however often it is pressed: the key is the card's own",
        f"{SRC}/connectors/food_order.py",
        'idempotency_key=f"menu-{args.card_id}",',
        'idempotency_key=f"menu-{new_card_id()}",',
        MENU_CARD,
    ),
    Mutation(
        "the order from a card carries no price the card could set",
        f"{SRC}/connectors/food_order.py",
        "class OrderFromMenu(Strict):",
        'class OrderFromMenu(Strict, extra="allow"):',
        MENU_CARD,
    ),
    Mutation(
        "a card is named by 32 hex characters, so it cannot be another card's key by accident",
        f"{SRC}/connectors/food_order.py",
        'pattern=rf"^[0-9a-f]{{{CARD_ID_HEX}}}$",',
        'pattern=r".*",',
        MENU_CARD,
    ),
    Mutation(
        "each search gives its card an id of its own",
        f"{SRC}/food/view.py",
        "return secrets.token_hex(CARD_ID_HEX // 2)",
        'return "0" * CARD_ID_HEX',
        MENU_CARD,
    ),
    Mutation(
        "the model is told the card shows the menu and not to list it",
        f"{SRC}/food/view.py",
        '"match. The card shows them and the person orders from it; do not list the items or prices."',
        '"match."',
        MENU_CARD,
    ),
    Mutation(
        "the model is given no item name from the menu",
        f"{SRC}/connectors/food_order.py",
        "return plain_result(menu_line(found), menu_view(found, new_card_id()))",
        'return plain_result(", ".join(i.name for i in found), menu_view(found, new_card_id()))',
        MENU_CARD,
    ),
    Mutation(
        "an item image is offered only from an origin the view declares",
        f"{SRC}/food/view.py",
        'if item.image_url and item.image_url.startswith(tuple(f"{origin}/" for origin in origins)):',
        "if item.image_url:",
        MENU_CARD,
    ),
    Mutation(
        "the view declares the origins its images load from",
        f"{SRC}/food/view.py",
        "    if origins:",
        "    if False:",
        MENU_CARD,
    ),
]
