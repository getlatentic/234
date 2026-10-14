# SPDX-License-Identifier: AGPL-3.0-or-later
"""Airtime through Index (`quick_buy`, category airtime): one offer, paid for any amount within the
merchant's limits. Index has no preview of airtime, so the quote is made from the amount and the person's
Zap balance, and the one call to `quick_buy` is the order, placed only after the person approves."""

from ...mask import group_phone
from ...vtpass.phone import normalise_phone
from ..model import Basket, Merchant, Offer, Totals
from ..pricing import assert_order_within_limits, price_lines
from .catalog import Entry
from .purchase import Preview, Purchase, zap_funding
from .reading import whole_naira

OFFER_ID = "airtime"


def offers_of(merchant: Merchant, entry: Entry) -> list[Offer]:
    return [
        Offer(
            merchant.id,
            OFFER_ID,
            entry.name,
            "Any amount within the merchant's limits, for any phone number.",
            "airtime recharge top-up",
            "open",
            None,
            None,
            None,
            True,
            1,
        )
    ]


async def price(preview: Preview, merchant: Merchant, entry: Entry, basket: Basket) -> Totals:
    offers = {offer.id: offer for offer in offers_of(merchant, entry)}
    lines = price_lines(merchant, offers, basket)
    total = sum(line.total_kobo for line in lines)
    assert_order_within_limits(merchant, total)
    phone = normalise_phone(basket.fields["phone"])
    purchase = Purchase(
        "airtime",
        "quick_buy",
        {"category": "airtime", "network": entry.code, "phone": phone, "amount_naira": whole_naira(total)},
        two_phase=False,
    )
    funding = await zap_funding(preview, total, purchase)
    fields = (("phone", "Phone number", group_phone(phone)),)
    return Totals(lines, (), fields, external=funding)
