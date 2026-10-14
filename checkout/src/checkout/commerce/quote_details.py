# SPDX-License-Identifier: AGPL-3.0-or-later
"""A `merchants` quote's details, and how it reads. The details are a copy of everything the server priced
(`quotes_are_fixed` keeps them), so a later change to an offer changes nothing a quote used. Lines, fees and
fields are shown to the person exactly as they are stored here."""

from typing import Any

from ..ledger import Quote
from ..money import format_naira
from .model import Merchant, Totals

TIMES = "\N{MULTIPLICATION SIGN}"
DESCRIPTION_LIMIT = 140


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
    }


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
    }


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
