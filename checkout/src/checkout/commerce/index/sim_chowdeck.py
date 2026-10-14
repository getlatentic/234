# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chowdeck through the simulated Index: linking by phone and code (`connect_merchant`), the nearby feed, a
restaurant's menu or a search (`find_items`), the three phases of `order` (`needs_options`, `needs_confirmation`,
then `confirmed` charges the person's Zap because the simulated Chowdeck wallet is empty) and `track_order`."""

from typing import Any

from .sim_catalog import DELIVERY_KOBO, OTP, PIN, vendors
from .sim_tools_base import SimContext, ToolAnswer, refusal, success

NOT_LINKED = (
    "Chowdeck is not linked. Ask the user for the phone number on their Chowdeck account, then call "
    "connect_merchant with merchant_id='chowdeck' and phone."
)
LINKED_ONLY = "chowdeck"


def _vendor_card(vendor: dict[str, Any]) -> dict[str, Any]:
    return {
        "vendor_id": vendor["vendor_id"],
        "name": vendor["name"],
        "open": vendor["open"],
        "delivery_fee_kobo": DELIVERY_KOBO,
    }


async def connect(ctx: SimContext, args: dict[str, Any]) -> ToolAnswer:
    if ctx.account is None:
        return refusal("This needs a person's own Index account.")
    if args["merchant_id"] != LINKED_ONLY:
        return refusal("Only chowdeck can be linked here.")
    phone = args.get("phone")
    if not phone:
        return refusal("Chowdeck links by phone: pass the phone number on the Chowdeck account.")
    if "otp" not in args:
        await ctx.store.set_account(ctx.account.id, chowdeck_phone=phone)
        return success("OTP sent. Ask the user for it.", {"status": "otp_sent"})
    if args["otp"] != OTP or ctx.account.chowdeck_phone != phone:
        return refusal("That code is not right.")
    await ctx.store.set_account(ctx.account.id, chowdeck_linked=1)
    return success("Chowdeck is linked.", {"status": "linked"})


def _linked(ctx: SimContext, args: dict[str, Any]) -> ToolAnswer | None:
    if args.get("merchant_id", LINKED_ONLY) != LINKED_ONLY:
        return refusal("Only chowdeck can be searched.")
    if ctx.account is None or not ctx.account.chowdeck_linked:
        return refusal(NOT_LINKED)
    return None


def _matching(query: str) -> list[dict[str, Any]]:
    words = query.lower().split()
    found = []
    for vendor in vendors():
        items = [
            i for i in vendor["items"] if all(w in f"{i['name']} {vendor['name']}".lower() for w in words)
        ]
        if items:
            found.append({**vendor, "items": items})
    return found


async def find_items(ctx: SimContext, args: dict[str, Any]) -> ToolAnswer:
    if (problem := _linked(ctx, args)) is not None:
        return problem
    url = {"catalog_url": "https://index.paystack.com/catalog/simulated"}
    if args.get("query"):
        return success("Matches", {"vendors": _matching(str(args["query"])), **url})
    if "vendor_id" in args:
        found = next((v for v in vendors() if v["vendor_id"] == args["vendor_id"]), None)
        if found is None:
            return refusal("There is no such restaurant.")
        return success(
            found["name"],
            {"vendor": _vendor_card(found), "categories": [{"name": "Menu", "items": found["items"]}], **url},
        )
    limit = int(args.get("limit", 12))
    return success("Nearby", {"vendors": [_vendor_card(v) for v in vendors()][:limit], **url})


def _lines(ctx: SimContext, args: dict[str, Any]) -> tuple[list[dict[str, Any]], int, ToolAnswer | None]:
    vendor = next((v for v in vendors() if v["vendor_id"] == args.get("vendor_id")), None)
    if vendor is None or not vendor["open"] or not args.get("items"):
        return [], 0, refusal("Pick an open restaurant and at least one dish.")
    picked, total = [], 0
    for want in args["items"]:
        dish = next((i for i in vendor["items"] if i["item_id"] == want.get("item_id")), None)
        if dish is None:
            return [], 0, refusal("A dish is not on that menu.")
        total += dish["price_kobo"] * int(want.get("quantity", 1))
        picked.append({"want": want, "dish": dish})
    return picked, total, None


def _needs(picked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"item_id": p["dish"]["item_id"], "name": p["dish"]["name"], "groups": p["dish"]["modifier_groups"]}
        for p in picked
        if p["dish"].get("modifier_groups") and not p["want"].get("modifier_selections")
    ]


def _upcharge(picked: list[dict[str, Any]]) -> int:
    extra = 0
    for p in picked:
        for selection in p["want"].get("modifier_selections") or []:
            for group in p["dish"].get("modifier_groups", []):
                extra += sum(
                    o["price_kobo"] for o in group["options"] if o["item_id"] == selection.get("item_id")
                )
    return extra


async def order(ctx: SimContext, args: dict[str, Any]) -> ToolAnswer:
    if (problem := _linked(ctx, {"merchant_id": args["merchant_id"]})) is not None:
        return problem
    assert ctx.account is not None
    picked, items_total, bad = _lines(ctx, args)
    if bad is not None:
        return bad
    if needs := _needs(picked):
        return success(
            "Some dishes need a choice.", {"status": "needs_options", "items_needing_options": needs}
        )
    items_total += _upcharge(picked)
    total = items_total + DELIVERY_KOBO
    breakdown = {
        "items_total_kobo": items_total,
        "delivery_fee_kobo": DELIVERY_KOBO,
        "grand_total_kobo": total,
        "chowdeck_wallet_balance_kobo": 0,
        "payment_route": "zap_merchant_payment",
        "balance_after_kobo": ctx.account.zap_kobo - total,
    }
    if args.get("confirmed") is not True:
        return success("Preview", {"status": "needs_confirmation", **breakdown})
    placed = await ctx.charge(
        "order", args, total, {"payment_route": "zap_merchant_payment", "delivery_pin": PIN}
    )
    if placed.error or placed.data.get("status") != "completed":
        return placed
    return ToolAnswer({**placed.data, "payment_status": "completed"}, placed.text, fate=placed.fate)


async def track(ctx: SimContext, args: dict[str, Any]) -> ToolAnswer:
    if ctx.account is None:
        return refusal("This needs a person's own Index account.")
    found = await ctx.store.order(str(args.get("order_id")), ctx.account.id)
    if found is None:
        return refusal("There is no such order.")
    paid = "completed" if found["status"] == "completed" else found["status"]
    return success("Order status", {"status": "preparing", "payment_status": paid, "order_id": found["id"]})
