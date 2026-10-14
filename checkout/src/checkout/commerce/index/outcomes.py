# SPDX-License-Identifier: AGPL-3.0-or-later
"""What Index's answer to a placed order means, in the three outcomes a quote has (docs/commerce.md, rule 6):
delivered, failed, or pending. An error Index reports means it did not place the order; a status it names
decides; a status it names that 234 does not know is pending, never delivered. A prepaid token and a delivery
PIN are kept for the receipt."""

import re

from ..model import Outcome
from .purchase import Purchase
from .reading import flat, text_in, words
from .wire import ToolReply

DONE = ("success", "successful", "completed", "complete", "delivered", "paid", "confirmed", "placed", "ok")
WAITING = ("pending", "processing", "queued", "initiated", "in_progress", "awaiting", "awaiting_approval")
FAILED = (
    "failed", "failure", "error", "cancelled", "canceled", "declined", "rejected", "refunded", "reversed",
    "needs_confirmation", "needs_options",
)  # fmt: skip
TOKEN_NAMES = ("token", "recharge_token", "prepaid_token", "electricity_token")
TOKEN_SHAPE = re.compile(r"\b\d{4}(?:[ -]?\d{4}){3,5}\b")
ORDER = "Order"
TOKEN = "Prepaid token"
PIN = "Delivery PIN"
KINDS = {"delivered": DONE, "pending": WAITING, "failed": FAILED}


def named(status: str | None) -> str | None:
    """`delivered`, `pending` or `failed` for a status word of Index's; None for no word or an unknown one."""
    word = (status or "").strip().lower().replace(" ", "_").replace("-", "_")
    return next((kind for kind, words_ in KINDS.items() if word in words_), None)


def decided(data: dict, *names: str) -> str:
    """Delivered when Index names a status that is done or names none; pending when the word is unknown."""
    status = text_in(data, *names)
    if status is None:
        return "delivered"
    return named(status) or "pending"


def _lines(purchase: Purchase, reply: ToolReply, data: dict) -> tuple[tuple[str, str], ...]:
    found: list[tuple[str, str]] = []
    if order := text_in(data, "order_id", "reference", "order_reference", "id"):
        found.append((ORDER, words(order, 40)))
    if purchase.kind == "electricity" and purchase.arguments.get("meter_type") == "prepaid":
        token = text_in(data, *TOKEN_NAMES) or (TOKEN_SHAPE.search(reply.text) or [None])[0]
        found.append((TOKEN, words(token, 40) if token else "not in Index's answer: see your Index message"))
    if pin := text_in(data, "delivery_pin", "pin"):
        found.append((PIN, words(pin, 12)))
    return tuple(found)


def placed(purchase: Purchase, reply: ToolReply) -> Outcome:
    """The outcome of the call that charges."""
    if reply.is_error:
        return Outcome(
            "failed", f"Paystack Index did not place the order: {words(reply.text) or 'no reason given'}"
        )
    data = flat(reply.data)
    kind = decided(data, "status", "payment_status")
    if kind == "delivered" and named(text_in(data, "payment_status")) == "pending":
        kind = "pending"
    said = {
        "delivered": "Paystack Index placed the order.",
        "pending": "Paystack Index has the order and has not finished it.",
        "failed": f"Paystack Index reports the order failed: {words(reply.text) or 'no reason given'}",
    }[kind]
    return Outcome(kind, said, _lines(purchase, reply, data))
