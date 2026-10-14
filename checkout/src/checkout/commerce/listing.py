# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the model reads about the directory: a line for each merchant and each offer, headed by a notice that
the names are data. Every name, description and holder in them has been through `third_party` already
(directory_store.py); the merchant's `blurb` is 234's own words and is the only guidance in them."""

from ..money import format_naira
from .model import Merchant, Offer, OptionGroup
from .text import NOTICE

SHOWN_MERCHANTS = 20
SHOWN_OFFERS = 15

_STATUS_WORDS = {
    "coming_soon": "coming soon, so it cannot be quoted yet",
    "beta": "beta",
    "live": "live",
}


def status_words(merchant: Merchant) -> str:
    if merchant.requires_link:
        return "needs the person to connect an account first, so it cannot be quoted yet"
    return _STATUS_WORDS[merchant.status]


def merchant_line(merchant: Merchant) -> str:
    return (
        f"{merchant.id} | {merchant.name} | {merchant.category} | {status_words(merchant)} | {merchant.blurb}"
    )


def merchant_listing(merchants: list[Merchant]) -> str:
    shown = merchants[:SHOWN_MERCHANTS]
    more = len(merchants) - len(shown)
    tail = [f"{more} more: narrow with a category."] if more > 0 else []
    return "\n".join(
        [NOTICE, "id | name | category | status | when to choose it", *map(merchant_line, shown), *tail]
    )


def _price(offer: Offer, merchant: Merchant) -> str:
    match offer.price_kind:
        case "fixed":
            return format_naira(offer.price_kobo or 0)
        case "range":
            return (
                f"any amount from {format_naira(offer.min_kobo or 0)} to {format_naira(offer.max_kobo or 0)}"
            )
        case _:
            return f"any amount from {format_naira(merchant.min_kobo)} to {format_naira(merchant.max_kobo)}"


def _group(group: OptionGroup) -> str:
    count = f"{group.least}" if group.least == group.most else f"{group.least} to {group.most}"
    choices = ", ".join(f"{c.id} +{format_naira(c.delta_kobo)}" for c in group.choices)
    return f"{group.id} (choose {count}): {choices}"


def _options(offer: Offer) -> str:
    return f" | options {'; '.join(map(_group, offer.option_groups))}" if offer.option_groups else ""


def offer_line(offer: Offer, merchant: Merchant) -> str:
    if not offer.available:
        return f"{offer.id} | {offer.name} | sold out"
    amount = " | name the amount as amount_kobo" if offer.price_kind != "fixed" else ""
    return f"{offer.id} | {offer.name} | {_price(offer, merchant)}{amount}{_options(offer)}"


def _asks(merchant: Merchant) -> str:
    fields = [
        f"{f.name}{'' if f.required else ' (optional)'} = {f.label}"
        + (f", one of {', '.join(f.options)}" if f.options else "")
        for f in merchant.fields
    ]
    checks = (
        " It checks the account first: call check_account, then pass its check_id."
        if merchant.checks_account
        else ""
    )
    return f"Fields for create_quote: {'; '.join(fields) or 'none'}.{checks}"


def offer_listing(merchant: Merchant, offers: list[Offer]) -> str:
    shown = offers[:SHOWN_OFFERS]
    more = len(offers) - len(shown)
    fee = f" {merchant.fee_label}: {format_naira(merchant.fee_kobo)}." if merchant.fee_kobo else ""
    head = (
        f"{merchant.name} ({status_words(merchant)}). Orders of {format_naira(merchant.min_kobo)} to "
        f"{format_naira(merchant.max_kobo)}.{fee} {_asks(merchant)}"
    )
    tail = [f"{more} more: narrow with a query."] if more > 0 else []
    return "\n".join([NOTICE, head, "id | name | price", *(offer_line(o, merchant) for o in shown), *tail])
