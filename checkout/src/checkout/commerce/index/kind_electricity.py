# SPDX-License-Identifier: AGPL-3.0-or-later
"""Electricity through Index (`quick_buy`, category electricity). Index validates the meter with the
distribution company and returns the customer's name without charging (phase 1); 234 asks that at the account
check, with the least amount the merchant takes, and again with the real amount when it makes the quote, where
the name must be the one the person confirmed. Calling again with `confirmed` charges (phase 2), and only
`fulfil.py` does that."""

from collections.abc import Mapping
from dataclasses import replace

from ...errors import DomainError
from ..checks import HOLDER_LIMIT
from ..model import AccountCheck, Basket, Merchant, Offer, Totals
from ..pricing import assert_order_within_limits, price_lines
from ..provider import AccountLookup
from ..text import third_party
from .catalog import Entry
from .purchase import Preview, Purchase, zap_funding
from .reading import flat, kobo_in, text_in, whole_naira, words
from .wire import IndexMisread, ToolReply

OFFER_ID = "electricity"
HOLDER_NAMES = ("customer_name", "account_name", "holder_name", "name")


def offers_of(merchant: Merchant, entry: Entry) -> list[Offer]:
    return [
        Offer(
            merchant.id,
            OFFER_ID,
            entry.name,
            "Prepaid or postpaid, for any amount within the merchant's limits.",
            "electricity power light meter prepaid postpaid",
            "open",
            None,
            None,
            None,
            True,
            1,
        )
    ]


def _arguments(entry: Entry, fields: Mapping[str, str], amount_kobo: int) -> dict[str, object]:
    return {
        "category": "electricity",
        "disco": entry.code,
        "meter_type": fields["meter_type"],
        "meter_number": fields["meter_number"],
        "amount_naira": whole_naira(amount_kobo),
    }


def _holder(reply: ToolReply) -> str:
    name = text_in(flat(reply.data), *HOLDER_NAMES)
    if name is None:
        raise IndexMisread("Index did not say whose meter it is.")
    return third_party(name, HOLDER_LIMIT)


def _not_found(merchant: Merchant, reply: ToolReply) -> DomainError:
    return DomainError(
        "ACCOUNT_NOT_FOUND",
        f"Paystack Index could not validate that meter with {merchant.name}: {words(reply.text, 120)}. "
        f"Nothing "
        "was charged. Ask the person to check the meter number and whether it is prepaid or postpaid.",
    )


async def check(
    preview: Preview, merchant: Merchant, entry: Entry, fields: Mapping[str, str]
) -> AccountLookup:
    reply = await preview.call("quick_buy", _arguments(entry, fields, merchant.min_kobo))
    if reply.is_error:
        raise _not_found(merchant, reply)
    return AccountLookup(_holder(reply))


async def price(
    preview: Preview, merchant: Merchant, entry: Entry, basket: Basket, check: AccountCheck
) -> Totals:
    lines = price_lines(merchant, {o.id: o for o in offers_of(merchant, entry)}, basket)
    total = sum(line.total_kobo for line in lines)
    assert_order_within_limits(merchant, total)
    reply = await preview.call("quick_buy", _arguments(entry, basket.fields, total))
    if reply.is_error:
        raise _not_found(merchant, reply)
    if _holder(reply).casefold() != check.holder_name.casefold():
        raise DomainError(
            "CHECK_MISMATCH", "Index now names a different holder for that meter. Check the account again."
        )
    read = kobo_in(flat(reply.data), "amount")
    if read is not None and read != total:
        raise IndexMisread("Index read a different amount than the one asked.")
    purchase = Purchase("electricity", "quick_buy", _arguments(entry, basket.fields, total), two_phase=True)
    funding = await zap_funding(preview, total, purchase)
    after = kobo_in(flat(reply.data), "balance_after")
    shown = tuple((s.name, s.label, basket.fields[s.name]) for s in merchant.fields)
    external = funding if after is None else replace(funding, balance_after_kobo=after)
    return Totals(lines, (), shown, check.holder_name, check.id, external)
