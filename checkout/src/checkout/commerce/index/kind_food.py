# SPDX-License-Identifier: AGPL-3.0-or-later
"""Food from Chowdeck through Index (`find_items`, `order`). A search names restaurants and dishes; an order is
for the dishes of one restaurant, and Index previews it in phases that charge nothing: `needs_options` (a dish
has a required choice), then `needs_confirmation` with the breakdown (dishes, delivery, total, and what pays).
234 quotes that breakdown, so the total is Index's own. Calling `order` again with `confirmed` places it, and
only `fulfil.py` does that."""

from collections.abc import Mapping
from typing import Any

from ...errors import DomainError
from ...money import Kobo
from ..model import Basket, ExternalFunding, Fee, Merchant, Offer, PricedLine, Totals
from ..pricing import assert_order_within_limits, merged, price_lines
from .food_menu import Vendor, ids_of, modifier_of, vendors_of
from .purchase import Preview, Purchase, refused
from .reading import flat, kobo_in, listing, need_kobo, text_in, words
from .wire import IndexMisread

MERCHANT = "chowdeck"
FEED_LIMIT = 12
MENUS_SHOWN = 3
ZAP_ROUTES = ("zap_merchant_payment", "zap")
SOURCES = {"zap": "your Zap balance at Paystack Index", "chowdeck": "your Chowdeck wallet"}


async def _vendors(preview: Preview, merchant_id: str, arguments: dict[str, Any], vendor: int | None = None):
    reply = await preview.call("find_items", {"merchant_id": MERCHANT, **arguments})
    if reply.is_error:
        raise refused(reply, "INDEX_REFUSED", "list Chowdeck's menu", "Chowdeck")
    return vendors_of(merchant_id, reply, vendor)


async def menu_of(preview: Preview, merchant_id: str, vendor_id: int) -> Vendor:
    found = await _vendors(preview, merchant_id, {"vendor_id": vendor_id}, vendor_id)
    if not found:
        raise DomainError("MERCHANT_NOT_AVAILABLE", "Chowdeck has no menu for that restaurant right now.")
    return found[0]


async def offers_of(preview: Preview, merchant: Merchant, query: str | None) -> list[Offer]:
    if query:
        found = await _vendors(preview, merchant.id, {"query": query})
        return [offer for vendor in found if vendor.open for offer in vendor.offers]
    nearby = await _vendors(preview, merchant.id, {"limit": FEED_LIMIT})
    menus = [await menu_of(preview, merchant.id, v.id) for v in [v for v in nearby if v.open][:MENUS_SHOWN]]
    return [offer for vendor in menus for offer in vendor.offers]


def _restaurant(merchant: Merchant, basket: Basket) -> int:
    vendors = {ids[0] for line in merged(basket.lines) if (ids := ids_of(line.offer_id))}
    if len(vendors) != 1 or any(ids_of(line.offer_id) is None for line in basket.lines):
        raise DomainError(
            "INVALID_INPUT",
            f"{merchant.name} takes the dishes of one restaurant in an order. Pass offer_ids from find_items, "
            "all from the same restaurant.",
        )
    return vendors.pop()


def _item(line: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"item_id": ids_of(line.offer_id)[1], "quantity": line.quantity}
    if line.options:
        item["modifier_selections"] = [modifier_of(option) for option in line.options]
    return item


def _arguments(vendor: int, basket: Basket) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "merchant_id": MERCHANT,
        "vendor_id": vendor,
        "items": [_item(line) for line in merged(basket.lines)],
    }
    if basket.fields.get("delivery_to"):
        arguments["address_query"] = basket.fields["delivery_to"]
    return arguments


def _needs_options(data: dict[str, Any]) -> DomainError:
    wanted = []
    for dish in listing(data, "items_needing_options"):
        for group in listing(dish, "groups", "required_groups") if isinstance(dish, dict) else []:
            options = ", ".join(
                f"{group.get('menu_group_id')}:{o.get('item_id')} ({words(str(o.get('name', '')), 30)})"
                for o in listing(group, "options")
                if isinstance(o, dict)
            )
            wanted.append(
                f"{words(str(dish.get('name', 'a dish')), 40)}, {words(str(group.get('name', '')), 30)}: {options}"
            )
    return DomainError(
        "OPTIONS_REQUIRED",
        "Chowdeck needs a choice for: " + "; ".join(wanted) + ". Ask the person, then quote again with the "
        "chosen option ids in `options` on that line. Nothing was charged.",
    )


def _funding(data: dict[str, Any], purchase: Purchase) -> ExternalFunding:
    route = str(text_in(data, "payment_route", "pays_with", "route") or "").lower()
    source = SOURCES["zap"] if any(word in route for word in ZAP_ROUTES) else SOURCES["chowdeck"]
    if not route:
        source = "your Chowdeck wallet or Zap balance, as Chowdeck chooses"
    return ExternalFunding(source, kobo_in(data, "balance_after"), purchase.terms())


def _totals(lines: tuple[PricedLine, ...], data: dict[str, Any], fields, purchase: Purchase) -> Totals:
    total = need_kobo(data, "the order's total", "grand_total", "total")
    delivery = kobo_in(data, "delivery_fee", "delivery") or 0
    other = total - sum(line.total_kobo for line in lines) - delivery
    fees = [Fee("Delivery", delivery)] if delivery else []
    if other:
        fees.append(Fee("Other charges" if other > 0 else "Discount", other))
    return Totals(lines, tuple(fees), fields, external=_funding(data, purchase))


async def price(preview: Preview, merchant: Merchant, basket: Basket) -> Totals:
    vendor = _restaurant(merchant, basket)
    menu = await menu_of(preview, merchant.id, vendor)
    if not menu.open:
        raise DomainError(
            "MERCHANT_NOT_AVAILABLE", f"{menu.name} is closed right now. Pick another restaurant."
        )
    lines = price_lines(merchant, {offer.id: offer for offer in menu.offers}, basket)
    arguments = _arguments(vendor, basket)
    reply = await preview.call("order", arguments)
    if reply.is_error:
        raise refused(reply, "ORDER_REFUSED", "price that order", "Chowdeck")
    data = flat(reply.data)
    status = str(data.get("status", ""))
    if data.get("needs_address_choice") or status == "needs_address_choice":
        raise DomainError(
            "ADDRESS_CHOICE",
            "Chowdeck needs to know which saved address: ask the person to describe it (home, office, an "
            "area) and pass that as delivery_to. Nothing was charged.",
        )
    if status == "needs_options":
        raise _needs_options(data)
    if status != "needs_confirmation":
        raise IndexMisread("Index did not preview the order.")
    totals = _totals(
        lines, data, _shown(merchant, basket, menu), Purchase("food", "order", arguments, two_phase=True)
    )
    assert_order_within_limits(merchant, totals.total_kobo)
    return totals


def _shown(merchant: Merchant, basket: Basket, menu: Vendor) -> tuple[tuple[str, str, str], ...]:
    delivery = tuple(
        (s.name, s.label, basket.fields[s.name]) for s in merchant.fields if s.name in basket.fields
    )
    return (("restaurant", "Restaurant", menu.name), *delivery)


async def previewed_total(preview: Preview, arguments: Mapping[str, Any]) -> Kobo:
    """What Index would charge for these arguments now, asked again just before the order is placed."""
    reply = await preview.call("order", arguments)
    if reply.is_error:
        raise refused(reply, "ORDER_REFUSED", "price that order", "Chowdeck")
    data = flat(reply.data)
    if data.get("status") != "needs_confirmation":
        raise IndexMisread("Index did not preview the order.")
    return need_kobo(data, "the order's total", "grand_total", "total")
