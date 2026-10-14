# SPDX-License-Identifier: AGPL-3.0-or-later
"""A `merchants` quote's details, and how it reads. The details are a copy of everything the server priced
(`quotes_are_fixed` keeps them), so a later change to an offer changes nothing a quote used. Lines, fees and
fields are shown to the person exactly as they are stored here."""

from typing import Any

from ..ledger import Quote
from ..modes import ModeInfo
from ..money import format_naira
from .model import Merchant, Totals

TIMES = "\N{MULTIPLICATION SIGN}"
DESCRIPTION_LIMIT = 140
EXTERNAL = "external"


def details_of(merchant: Merchant, totals: Totals) -> dict[str, Any]:
    return {
        "kind": "basket",
        "provider": merchant.provider,
        "merchantId": merchant.id,
        "category": merchant.category,
        "lines": [
            {
                "offerId": line.offer_id,
                "name": line.name,
                "quantity": line.quantity,
                "unitKobo": line.unit_kobo,
                "options": list(line.options),
            }
            for line in totals.lines
        ],
        "fees": [{"label": fee.label, "kobo": fee.kobo} for fee in totals.fees],
        "subtotalKobo": totals.subtotal_kobo,
        "fields": [{"name": name, "label": label, "value": value} for name, label, value in totals.fields],
        "holder": totals.holder_name,
        "checkId": totals.check_id,
        **_external_details(totals),
        **({"order": dict(totals.order)} if totals.order else {}),
    }


def _external_details(totals: Totals) -> dict[str, Any]:
    """What a quote paid from the buyer's own account at the provider keeps: whose money, what is left of it,
    and what the provider needs to place the order once the person approves."""
    external = totals.external
    if external is None:
        return {}
    return {
        "funding": EXTERNAL,
        "paidFrom": external.source,
        "balanceAfterKobo": external.balance_after_kobo,
        "index": dict(external.terms),
    }


def is_external(quote: Quote) -> bool:
    """Whether the buyer's own account at the provider pays this quote: no wallet, no checkout."""
    return quote.details.get("funding") == EXTERNAL


def external_mode(quote: Quote) -> ModeInfo | None:
    """What kind of money an externally paid quote moves: the person's own, or nobody's in the simulator."""
    if not is_external(quote):
        return None
    if quote.details["index"].get("live"):
        return ModeInfo("Paystack Index: your own account, real money", False)
    return ModeInfo("Simulated Paystack Index: no money moves", True)


def describe(totals: Totals) -> str:
    """What the order is, for the model and the log: its lines, shortened."""
    text = ", ".join(f"{line.quantity} x {line.name}" for line in totals.lines)
    return (
        text
        if len(text) <= DESCRIPTION_LIMIT
        else f"{text[: DESCRIPTION_LIMIT - 1].rstrip()}\N{HORIZONTAL ELLIPSIS}"
    )


def basket_view(quote: Quote) -> dict[str, Any]:
    """The card's picture of the details: a line per item with its options, a line per fee, the buyer's
    fields, and the holder's name where the provider checked an account."""
    d = quote.details
    return {
        "kind": "basket",
        "merchant": quote.merchant,
        "lines": [
            {
                "name": line["name"],
                "options": line["options"],
                "quantity": line["quantity"],
                "unit": format_naira(line["unitKobo"]),
                "total": format_naira(line["unitKobo"] * line["quantity"]),
            }
            for line in d["lines"]
        ],
        "fees": [{"label": fee["label"], "amount": format_naira(fee["kobo"])} for fee in d["fees"]],
        "subtotal": format_naira(d["subtotalKobo"]),
        "fields": [{"label": f["label"], "value": f["value"]} for f in d["fields"]],
        "holder": d["holder"],
        "paidFrom": d.get("paidFrom"),
        "balanceAfter": _after(d),
    }


def _after(details: dict[str, Any]) -> str | None:
    after = details.get("balanceAfterKobo")
    return format_naira(after) if after is not None else None


def _chosen(line: dict[str, Any]) -> str:
    return f" ({', '.join(line['options'])})" if line["options"] else ""


def receipt_lines(quote: Quote) -> list[tuple[str, str]]:
    """The items and fees of a delivered order, as a receipt reads them."""
    d = quote.details
    items = [
        (
            f"{line['quantity']} {TIMES} {line['name']}{_chosen(line)}",
            format_naira(line["unitKobo"] * line["quantity"]),
        )
        for line in d["lines"]
    ]
    fees = [(fee["label"], format_naira(fee["kobo"])) for fee in d["fees"]]
    return [*items, *fees, ("Total", format_naira(quote.amount_kobo))]


def funding_lines(quote: Quote) -> list[tuple[str, str]]:
    """Where the money came from, when it was not 234's to hold."""
    paid_from = quote.details.get("paidFrom")
    return [("Paid from", paid_from)] if paid_from else []
