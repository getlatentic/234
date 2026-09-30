# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the menu card is given: the menu as data. A price here is for display; the order that follows
carries item ids and quantities only, and the server prices them again."""

import secrets
from typing import Any

from .menu import DELIVERY_AREAS, DELIVERY_FEE_KOBO, IMAGE_ORIGINS, RESTAURANT, MenuItem

CARD_ID_HEX = 32


def new_card_id() -> str:
    """Names one menu card. It is also the basis of the order's idempotency key, so a card makes one order."""
    return secrets.token_hex(CARD_ID_HEX // 2)


def _shown(item: MenuItem, origins: tuple[str, ...]) -> dict[str, Any]:
    shown: dict[str, Any] = {
        "item_id": item.id,
        "name": item.name,
        "note": item.description,
        "price_kobo": item.price_kobo,
        "available": item.available,
        "category": item.category,
        "art": item.art,
    }
    if item.image_url and item.image_url.startswith(tuple(f"{origin}/" for origin in origins)):
        shown["image_url"] = item.image_url
    return shown


def menu_view(
    found: list[MenuItem], card_id: str, origins: tuple[str, ...] = IMAGE_ORIGINS
) -> dict[str, object]:
    """An image is offered only from an origin the view declares, since the card cannot load any other."""
    return {
        "card_id": card_id,
        "merchant": RESTAURANT,
        "items": [_shown(item, origins) for item in found],
        "areas": list(DELIVERY_AREAS),
        "delivery_fee_kobo": DELIVERY_FEE_KOBO,
    }


def menu_line(found: list[MenuItem]) -> str:
    """What the model reads: how many items match, and that the card shows them."""
    many = len(found)
    return (
        f"{RESTAURANT}, simulated merchant (not Chowdeck): {many} item{'' if many == 1 else 's'} "
        "match. The card shows them and the person orders from it; do not list the items or prices."
    )


def view_meta(origins: tuple[str, ...] = IMAGE_ORIGINS) -> dict[str, Any]:
    """The menu view's `_meta.ui`: no border, and the origins its images may load from, if any."""
    meta: dict[str, Any] = {"prefersBorder": False}
    if origins:
        meta["csp"] = {"resourceDomains": list(origins)}
    return meta
