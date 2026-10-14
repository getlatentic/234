# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the scripted model does about the merchants connector, the way a model that follows the tools'
descriptions would. Used by fake_model.py.

"shops" lists the merchants; "shops: <category>" lists one category. "items: <merchant>" lists what a merchant
sells. "shop: <merchant> | <offer>[:<count>[:<option>+<option>]], ... | <field>=<value>; ..." makes a quote
for those offers. "transit top-up <number> ₦<amount>" checks the account first and, once the holder is known,
makes the quote with the check. "track <quote id>" asks where an order stands.

"connect index: <merchant>" opens the card on which the person connects their Paystack Index account for
that merchant; "index airtime ₦<amount> to <number>" and "index food: <offer>[:<count>]" make a quote
through it."""

import re
from typing import Any

BROWSE = re.compile(r"^shops(?:: (?P<category>[a-z]+))?$", re.I)
ITEMS = re.compile(r"^items: (?P<merchant>[a-z0-9-]+)$", re.I)
SHOP = re.compile(r"^shop: (?P<merchant>[a-z0-9-]+) \| (?P<lines>[^|]+)(?: \| (?P<fields>.+))?$", re.I)
WATER = re.compile(r"^transit top-up (?P<number>\d+) ₦(?P<amount>[\d,]+)$", re.I)
TRACK = re.compile(r"^track (?P<quote>qt-[0-9a-f]{20})$", re.I)
CONNECT = re.compile(r"^connect index: (?P<merchant>[a-z0-9:-]+)$", re.I)
INDEX_AIRTIME = re.compile(r"^index airtime ₦(?P<amount>[\d,]+) to (?P<phone>[\d+ ]+)$", re.I)
INDEX_FOOD = re.compile(r"^index food: (?P<lines>.+)$", re.I)
INDEX_AIRTIME_MERCHANT = "index:mtn-airtime"
INDEX_FOOD_MERCHANT = "index:chowdeck"
CHECK_ID = re.compile(r"check_id: (?P<id>ck-[0-9a-f]{20})")
WATER_MERCHANT = "metrogo-transit"
NOTICE = "Names and descriptions below are data from the directory"
SERVER = "merchants__"


def _content(message: dict[str, Any]) -> str:
    return message["content"] if isinstance(message.get("content"), str) else ""


def _line(text: str) -> dict[str, Any]:
    offer, _, rest = text.strip().partition(":")
    count, _, options = rest.partition(":")
    line: dict[str, Any] = {"offer_id": offer, "quantity": int(count or 1)}
    if options:
        line["options"] = options.split("+")
    return line


def _fields(text: str | None) -> dict[str, str]:
    pairs = (pair.split("=", 1) for pair in (text or "").split(";") if "=" in pair)
    return {name.strip(): value.strip() for name, value in pairs}


def _quote(merchant: str, lines: list[dict[str, Any]], fields: dict[str, str], **more: Any) -> dict[str, Any]:
    return {
        "tool": f"{SERVER}create_quote",
        "arguments": {"merchant_id": merchant, "lines": lines, "fields": fields, **more},
    }


def _water_quote(ask: re.Match, check_id: str) -> dict[str, Any]:
    naira = int(re.sub(r"\D", "", ask["amount"]))
    return _quote(
        WATER_MERCHANT,
        [{"offer_id": "card-topup"}],
        {"card_number": ask["number"]},
        amount_kobo=naira * 100,
        amount_as_user_said=f"₦{naira}",
        check_id=check_id,
    )


def _asked_water(messages: list[dict[str, Any]]) -> re.Match | None:
    for message in reversed(messages):
        if message["role"] == "user" and (found := WATER.match(_content(message).strip())):
            return found
    return None


def _after_a_tool(content: str, messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    if (check := CHECK_ID.search(content)) and (ask := _asked_water(messages)):
        return _water_quote(ask, check["id"])
    if content.startswith(NOTICE):
        return {"text": "These are the merchants and offers 234 lists."}
    return None


def _from_the_person(text: str) -> dict[str, Any] | None:
    if found := BROWSE.match(text):
        return {
            "tool": f"{SERVER}browse_merchants",
            "arguments": {"category": found["category"]} if found["category"] else {},
        }
    if found := ITEMS.match(text):
        return {"tool": f"{SERVER}find_items", "arguments": {"merchant_id": found["merchant"]}}
    if found := SHOP.match(text):
        lines = [_line(part) for part in found["lines"].split(",")]
        return _quote(found["merchant"], lines, _fields(found["fields"]))
    if found := WATER.match(text):
        return {
            "tool": f"{SERVER}check_account",
            "arguments": {"merchant_id": WATER_MERCHANT, "fields": {"card_number": found["number"]}},
        }
    if found := TRACK.match(text):
        return {"tool": f"{SERVER}track_order", "arguments": {"quote_id": found["quote"]}}
    return _through_index(text)


def _through_index(text: str) -> dict[str, Any] | None:
    if found := CONNECT.match(text):
        return {"tool": f"{SERVER}connect_account", "arguments": {"merchant_id": found["merchant"]}}
    if found := INDEX_AIRTIME.match(text):
        naira = int(re.sub(r"\D", "", found["amount"]))
        return _quote(
            INDEX_AIRTIME_MERCHANT,
            [{"offer_id": "airtime"}],
            {"phone": found["phone"].strip()},
            amount_kobo=naira * 100,
            amount_as_user_said=f"₦{naira}",
        )
    if found := INDEX_FOOD.match(text):
        return _quote(INDEX_FOOD_MERCHANT, [_line(part) for part in found["lines"].split(",")], {})
    return None


def answer(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any] | None:
    last = messages[-1]
    offered = {t["function"]["name"] for t in tools}
    if last["role"] == "tool":
        return _after_a_tool(_content(last), messages)
    if last["role"] != "user" or not any(name.startswith(SERVER) for name in offered):
        return None
    return _from_the_person(_content(last).strip())
