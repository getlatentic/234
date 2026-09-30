# SPDX-License-Identifier: AGPL-3.0-or-later
"""The record a person keeps of a finished quote."""

from datetime import UTC, datetime
from typing import Any

from .clock import format_lagos
from .ledger import Quote
from .mask import group_phone, mask_account
from .money import format_naira
from .network import NETWORK_LABEL

TIMES = "\N{MULTIPLICATION SIGN}"
Line = tuple[str, str | None]


def _paid_at(quote: Quote) -> str | None:
    iso = quote.progress.get("paidAt")
    if not iso:
        return None
    moment = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(UTC)
    return format_lagos(int(moment.timestamp() * 1000))


def _payment(quote: Quote, mode: str) -> tuple[str, list[Line]]:
    return "Payment received", [
        ("Amount", format_naira(quote.amount_kobo)),
        ("For", quote.description),
        ("Merchant", quote.merchant),
        ("Paid", _paid_at(quote)),
        ("Reference", quote.progress.get("paystackReference")),
        ("Mode", mode),
    ]


def _transfer(quote: Quote, mode: str) -> tuple[str, list[Line]]:
    d = quote.details
    return "Transfer sent", [
        ("Amount", format_naira(quote.amount_kobo)),
        ("To", d["recipientName"]),
        ("Bank", d["bankName"]),
        ("Account", mask_account(d["accountNumber"])),
        ("Reference", quote.progress.get("transferReference")),
        ("Mode", mode),
    ]


def _delivered(title: str, extra: list[Line], quote: Quote, mode: str) -> tuple[str, list[Line]]:
    d = quote.details
    return title, [
        ("Amount", format_naira(quote.amount_kobo)),
        *extra,
        ("Network", NETWORK_LABEL[d["network"]]),
        ("Number", group_phone(d["phone"])),
        ("Paid", _paid_at(quote)),
        ("Payment reference", quote.progress.get("paystackReference")),
        ("VTpass request", (quote.progress.get("fulfilment") or {}).get("requestId")),
        ("Mode", mode),
    ]


def _airtime(quote: Quote, mode: str) -> tuple[str, list[Line]]:
    return _delivered("Airtime delivered", [], quote, mode)


def _data(quote: Quote, mode: str) -> tuple[str, list[Line]]:
    return _delivered("Data delivered", [("Plan", quote.details["planName"])], quote, mode)


def _food(quote: Quote, mode: str) -> tuple[str, list[Line]]:
    d = quote.details
    ordered = [
        (f"{line['quantity']} {TIMES} {line['name']}", format_naira(line["unitKobo"] * line["quantity"]))
        for line in d["lines"]
    ]
    return "Order delivered", [
        *ordered,
        ("Delivery", format_naira(d["deliveryFeeKobo"])),
        ("Total", format_naira(quote.amount_kobo)),
        ("Delivered to", d["area"]),
        ("Paid", _paid_at(quote)),
        ("Payment reference", quote.progress.get("paystackReference")),
        ("Mode", mode),
    ]


_BUILDERS = {"payment": _payment, "transfer": _transfer, "airtime": _airtime, "data": _data, "food": _food}


def receipt_for(quote: Quote, mode_label: str) -> dict[str, Any] | None:
    if quote.state != "settled":
        return None
    title, lines = _BUILDERS[quote.details["kind"]](quote, mode_label)
    return {"title": title, "lines": [{"label": k, "value": v} for k, v in lines if v is not None]}
