# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the `vtpass` provider's merchants sell. Television bouquets and their prices are VTpass's, read from
its `service-variations` each time, so the price a quote is made at is the one VTpass charges; DStv and GOtv
also sell a renewal of the bouquet on the card, whose price is the account check's. Electricity is one offer
paid for any amount: the least comes from the meter's account check and no most is assumed. Every name
VTpass wrote passes `third_party`."""

import re

from ..errors import DomainError
from ..vtpass.api import VtpassApi, VtpassError
from ..vtpass.bills import RENEWABLE, SERVICES
from .model import Merchant, Offer, PriceKind
from .text import third_party

RENEW = "renew"
ELECTRICITY = "electricity"
NAME_LIMIT = 80
CODE_LIMIT = 60
_WORD = re.compile(r"[^a-z0-9]+")


def _offer(
    merchant: Merchant, offer_id: str, name: str, kind: PriceKind, price_kobo: int | None, tags: str
) -> Offer:
    return Offer(merchant.id, offer_id, name, "", tags, kind, price_kobo, None, None, True, 1)


def _electricity(merchant: Merchant) -> list[Offer]:
    return [
        _offer(
            merchant,
            ELECTRICITY,
            "Electricity purchase",
            "open",
            None,
            "electricity prepaid postpaid token units",
        )
    ]


async def _bouquets(api: VtpassApi, merchant: Merchant) -> list[Offer]:
    try:
        found = await api.bouquets(merchant.id)
    except VtpassError as error:
        raise DomainError("PROVIDER_ERROR", f"VTpass could not list the bouquets: {error}") from error
    return [
        _offer(
            merchant,
            third_party(b.code, CODE_LIMIT),
            third_party(b.name, NAME_LIMIT),
            "fixed",
            b.amount_kobo,
            "",
        )
        for b in found
    ]


def _matches(offer: Offer, query: str | None) -> bool:
    words = [word for word in _WORD.split((query or "").lower()) if word]
    text = f"{offer.id} {offer.name} {offer.tags}".lower()
    return all(word in text for word in words)


async def vtpass_offers(api: VtpassApi, merchant: Merchant, query: str | None = None) -> list[Offer]:
    """The merchant's offers in order, those holding every word of `query` when there is one."""
    if SERVICES[merchant.id][0] == "electricity":
        offers = _electricity(merchant)
    else:
        offers = await _bouquets(api, merchant)
        if merchant.id in RENEWABLE:
            renewal = _offer(
                merchant, RENEW, "Renew the current bouquet", "renewal", None, "renew renewal subscription"
            )
            offers = [renewal, *offers]
    return [offer for offer in offers if _matches(offer, query)]
