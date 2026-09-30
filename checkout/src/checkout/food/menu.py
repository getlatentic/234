# SPDX-License-Identifier: AGPL-3.0-or-later
"""An invented Lagos menu, prices in kobo. The prices are plausible, not Chowdeck's or any restaurant's.
Quantities come from the caller; prices never do. An item can be sold out: it is listed, and never priced
into a basket. `art` names the drawing the card shows for it; a real merchant sets `image_url` instead."""

import re
from dataclasses import dataclass

from ..errors import DomainError
from ..money import Kobo, format_naira

RESTAURANT = "Mama Put Yaba (simulated)"
DELIVERY_FEE_KOBO: Kobo = 120_000
DELIVERY_AREAS = ("Yaba", "Surulere", "Ikeja GRA", "Maryland", "Lekki Phase 1", "Victoria Island", "Ikoyi")
MAX_PER_ITEM = 10
MAX_LINES = 12
IMAGE_ORIGINS: tuple[str, ...] = ()


CATEGORIES = ("mains", "soups", "sides", "drinks")
ART = ("plate", "soup", "skewer", "wrap", "dough", "cup", "bottle")


@dataclass(frozen=True)
class MenuItem:
    id: str
    name: str
    description: str
    price_kobo: Kobo
    category: str
    art: str
    tags: tuple[str, ...]
    available: bool = True
    image_url: str | None = None


def _item(
    item_id: str,
    name: str,
    description: str,
    naira: int,
    category: str,
    art: str,
    *tags: str,
    sold_out: bool = False,
) -> MenuItem:
    return MenuItem(item_id, name, description, naira * 100, category, art, tags, not sold_out)


MENU: tuple[MenuItem, ...] = (
    _item(
        "jollof-chicken",
        "Jollof rice with fried chicken",
        "Party jollof, one piece of chicken, fried plantain",
        4500,
        "mains", "plate",
        "rice", "chicken", "meal",
    ),
    _item(
        "fried-rice-dodo",
        "Fried rice, dodo and grilled chicken",
        "Fried rice with peppered chicken and dodo",
        4800,
        "mains", "plate",
        "rice", "chicken", "meal",
    ),
    _item(
        "egusi-pounded-yam",
        "Egusi soup with pounded yam",
        "Egusi with assorted meat, two wraps of pounded yam",
        5200,
        "soups", "soup",
        "soup", "swallow", "meal", "spicy",
    ),
    _item(
        "amala-ewedu",
        "Amala, ewedu and gbegiri",
        "With assorted meat and stew",
        4200,
        "soups", "soup",
        "swallow", "soup", "meal", "spicy",
        sold_out=True,
    ),
    _item(
        "beef-suya",
        "Beef suya, 200g",
        "Grilled beef with onions, tomato and yaji",
        3500,
        "mains", "skewer",
        "suya", "beef", "grill", "spicy", "snack",
    ),
    _item(
        "catfish-pepper-soup",
        "Catfish pepper soup",
        "Hot pepper soup with fresh catfish",
        6000,
        "soups", "soup",
        "soup", "fish", "spicy",
    ),
    _item(
        "moi-moi", "Moi moi, 2 wraps", "Steamed bean pudding with egg", 1500,
        "sides", "wrap", "beans", "snack", "side",
    ),
    _item(
        "puff-puff", "Puff puff, 6 pieces", "Sweet fried dough balls", 1000,
        "sides", "dough", "snack", "sweet", "side",
    ),
    _item("zobo", "Zobo, 500ml", "Chilled hibiscus drink with ginger", 800, "drinks", "cup", "drink"),
    _item(
        "chapman", "Chapman, 500ml", "Fruity non-alcoholic cocktail", 1800, "drinks", "cup", "drink", "sweet"
    ),
    _item("water", "Bottled water, 75cl", "Still water", 300, "drinks", "bottle", "drink"),
)  # fmt: skip


@dataclass(frozen=True)
class BasketLine:
    item_id: str
    name: str
    quantity: int
    unit_kobo: Kobo

    def as_detail(self) -> dict[str, object]:
        return {
            "itemId": self.item_id,
            "name": self.name,
            "quantity": self.quantity,
            "unitKobo": self.unit_kobo,
        }


@dataclass(frozen=True)
class PricedBasket:
    lines: tuple[BasketLine, ...]
    subtotal_kobo: Kobo
    delivery_fee_kobo: Kobo

    @property
    def total_kobo(self) -> Kobo:
        return self.subtotal_kobo + self.delivery_fee_kobo


def search_menu(query: str | None, max_price_naira: int | None) -> list[MenuItem]:
    words = [w for w in re.split(r"[^a-z0-9]+", (query or "").lower()) if w]
    found = []
    for entry in MENU:
        haystack = f"{entry.name} {entry.description} {' '.join(entry.tags)}".lower()
        within = max_price_naira is None or entry.price_kobo <= max_price_naira * 100
        if within and all(word in haystack for word in words):
            found.append(entry)
    return found


def price_basket(requested: list[tuple[str, int]]) -> PricedBasket:
    """Prices a basket from the menu alone; a repeated item is merged."""
    if not requested or len(requested) > MAX_LINES:
        raise DomainError("INVALID_INPUT", f"A basket has 1 to {MAX_LINES} different items.")
    merged: dict[str, int] = {}
    for item_id, quantity in requested:
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= MAX_PER_ITEM:
            raise DomainError("INVALID_INPUT", f"Quantity must be a whole number from 1 to {MAX_PER_ITEM}.")
        merged[item_id] = merged.get(item_id, 0) + quantity
    lines = tuple(_line(item_id, quantity) for item_id, quantity in merged.items())
    subtotal = sum(line.unit_kobo * line.quantity for line in lines)
    return PricedBasket(lines, subtotal, DELIVERY_FEE_KOBO)


def _line(item_id: str, quantity: int) -> BasketLine:
    entry = next((m for m in MENU if m.id == item_id), None)
    if entry is None:
        raise DomainError(
            "INVALID_INPUT",
            f'There is no menu item "{item_id}". The person picks items on the menu card.',
        )
    if quantity > MAX_PER_ITEM:
        raise DomainError("INVALID_INPUT", f"At most {MAX_PER_ITEM} of one item.")
    if not entry.available:
        raise DomainError("ITEM_UNAVAILABLE", f"{entry.name} is sold out. Pick another item from the menu.")
    return BasketLine(item_id, entry.name, quantity, entry.price_kobo)


def describe_basket(basket: PricedBasket) -> str:
    lines = [f"{it.quantity} x {it.name}: {format_naira(it.unit_kobo * it.quantity)}" for it in basket.lines]
    return "\n".join(
        [
            *lines,
            f"Delivery: {format_naira(basket.delivery_fee_kobo)}",
            f"Total: {format_naira(basket.total_kobo)}",
        ]
    )


def assert_delivery_area(area: str) -> str:
    found = next((a for a in DELIVERY_AREAS if a.lower() == area.strip().lower()), None)
    if found is None:
        raise DomainError("INVALID_INPUT", f"{RESTAURANT} delivers to: {', '.join(DELIVERY_AREAS)}.")
    return found
