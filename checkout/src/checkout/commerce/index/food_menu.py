# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chowdeck's restaurants and dishes as Index's `find_items` returns them, read into 234's offers. A dish is the
offer `v<vendor id>-i<item id>`, so a quote names its restaurant and Index its dish without a table of ours;
a dish's required choices (size, spice) are option groups whose ids are `<group id>:<option id>`. Every name is
third-party text. Prices here are indicative: the order's preview is what is quoted."""

import re
from dataclasses import dataclass
from typing import Any

from ..model import Choice, Offer, OptionGroup
from ..text import third_party
from .reading import flat, kobo_in, listing
from .wire import ToolReply

OFFER = re.compile(r"v(\d+)-i(\d+)")
OPTION = re.compile(r"(\d+):(\d+)")
NAME_LIMIT = 80
VENDOR_LIMIT = 60


@dataclass(frozen=True)
class Vendor:
    id: int
    name: str
    open: bool
    offers: tuple[Offer, ...]


def offer_id(vendor_id: int, item_id: int) -> str:
    return f"v{vendor_id}-i{item_id}"


def ids_of(offer: str) -> tuple[int, int] | None:
    found = OFFER.fullmatch(offer)
    return (int(found[1]), int(found[2])) if found else None


def modifier_of(option: str) -> dict[str, int]:
    """The `modifier_selections` entry of an option id."""
    found = OPTION.fullmatch(option)
    return {"menu_group_id": int(found[1]), "item_id": int(found[2])} if found else {}


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _groups(raw: Any) -> tuple[OptionGroup, ...]:
    groups = []
    for group in raw if isinstance(raw, list) else []:
        gid = _int(group.get("menu_group_id")) if isinstance(group, dict) else None
        choices = tuple(
            Choice(f"{gid}:{oid}", third_party(str(o.get("name", oid)), 40), kobo_in(o, "price") or 0)
            for o in listing(group, "options", "items")
            if isinstance(o, dict) and (oid := _int(o.get("item_id"))) is not None
        )
        if gid is not None and choices:
            least = _int(group.get("min")) if group.get("required") else 0
            groups.append(
                OptionGroup(
                    str(gid),
                    third_party(str(group.get("name", gid)), 40),
                    least or 0,
                    _int(group.get("max")) or 1,
                    choices,
                )
            )
    return tuple(groups)


def _offer(merchant_id: str, vendor: int, vendor_name: str, raw: dict[str, Any]) -> Offer | None:
    item, price = _int(raw.get("item_id")), kobo_in(raw, "price")
    if item is None or price is None or price <= 0:
        return None
    return Offer(
        merchant_id,
        offer_id(vendor, item),
        third_party(str(raw.get("name", item)), NAME_LIMIT),
        f"at {vendor_name}",
        vendor_name.lower(),
        "fixed",
        price,
        None,
        None,
        raw.get("available") is not False,
        10,
        _groups(raw.get("modifier_groups") or raw.get("option_groups")),
    )


def _dishes(raw: dict[str, Any]) -> list[Any]:
    dishes = list(listing(raw, "items"))
    for category in listing(raw, "categories", "menu"):
        dishes.extend(listing(category, "items") if isinstance(category, dict) else [])
    return dishes


def _vendor(merchant_id: str, raw: dict[str, Any], fallback: int | None) -> Vendor | None:
    vendor = _int(raw.get("vendor_id")) if raw.get("vendor_id") is not None else fallback
    if vendor is None:
        return None
    name = third_party(str(raw.get("name") or raw.get("vendor_name") or f"restaurant {vendor}"), VENDOR_LIMIT)
    offers = tuple(
        offer
        for dish in _dishes(raw)
        if isinstance(dish, dict) and (offer := _offer(merchant_id, vendor, name, dish))
    )
    return Vendor(vendor, name, raw.get("open") is not False, offers)


def vendors_of(merchant_id: str, reply: ToolReply, vendor_id: int | None = None) -> list[Vendor]:
    """The restaurants in a `find_items` answer: a list of them for a search or the nearby feed, or the one
    whose menu was asked for."""
    data = flat(reply.data)
    listed = [
        v
        for raw in listing(data, "vendors", "restaurants")
        if isinstance(raw, dict) and (v := _vendor(merchant_id, raw, None))
    ]
    if listed or vendor_id is None:
        return listed
    raw = data["vendor"] if isinstance(data.get("vendor"), dict) else {}
    found = _vendor(merchant_id, {**data, **raw}, vendor_id)
    return [found] if found else []
