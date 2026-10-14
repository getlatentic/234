# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the model reads about the directory: a line for each merchant and each offer, headed by a notice that
the names are data. Every name, description and holder in them has been through `third_party` already
(directory_store.py); the merchant's `blurb` is 234's own words and is the only guidance in them."""

from ..money import format_naira
from .model import Merchant, Offer, OptionGroup
from .text import NOTICE

CHECKED_NEXT = (
    "If the person only asked what it sells or costs, answer that. If they want to buy, call check_account "
    "now with the account details they gave, then create_quote with the same fields, the check_id and the "
    "offer_id (an offer paid for any amount takes amount_kobo), and ask only for what is missing."
)
BUY_NEXT = (
    "If the person only asked what it sells or costs, answer that. If they want to buy, call create_quote "
    "now with the merchant_id, offer_ids, counts and those fields, and ask only for what is missing."
)
NONE_MATCH = "No offer matches {query!r}; everything it sells follows."
FIND_NEXT = "To see what one sells and what it needs to buy, call find_items with its id."
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


def _needs(merchant: Merchant) -> str:
    """The fields a buyer gives, by their names, so a model that never lists the offers still passes them."""
    names = [f.name for f in merchant.fields if f.required]
    if not names:
        return ""
    checked = ", after check_account" if merchant.checks_account else ""
    return f" Needs {', '.join(names)}{checked}."


def merchant_line(merchant: Merchant) -> str:
    return (
        f"{merchant.id} | {merchant.name} | {merchant.category} | {status_words(merchant)} | "
        f"{merchant.blurb}{_needs(merchant)}"
    )


def merchant_listing(
    merchants: list[Merchant], elsewhere: list[Merchant] | None = None, category: str | None = None
) -> str:
    """The merchants of the category asked for, and the names of the others, so a wrong guess of the
    category does not hide a merchant."""
    shown = merchants[:SHOWN_MERCHANTS]
    more = len(merchants) - len(shown)
    tail = [f"{more} more: narrow with a category."] if more > 0 else []
    others = [f"{m.id} | {m.name} | {m.category}" for m in elsewhere or []]
    other = [f"Also listed, in other categories: {'; '.join(others)}."] if others else []
    none = [f"No merchants are listed in {category}."] if category and not merchants else []
    table = ["id | name | category | status | when to choose it"] if merchants else []
    return "\n".join([NOTICE, *none, *table, *map(merchant_line, shown), *tail, *other, FIND_NEXT])


def _limits(merchant: Merchant) -> str:
    """The merchant's least and most for an order, or its least alone when it states no most."""
    least = format_naira(merchant.min_kobo)
    return f"{least} to {format_naira(merchant.max_kobo)}" if merchant.has_maximum else f"at least {least}"


def _price(offer: Offer, merchant: Merchant) -> str:
    match offer.price_kind:
        case "fixed":
            return format_naira(offer.price_kobo or 0)
        case "range":
            return (
                f"any amount from {format_naira(offer.min_kobo or 0)} to {format_naira(offer.max_kobo or 0)}"
            )
        case "renewal":
            return "the renewal amount that check_account returns for the card"
        case _:
            return f"any amount {'from ' if merchant.has_maximum else ''}{_limits(merchant)}"


def _group(group: OptionGroup) -> str:
    count = f"{group.least}" if group.least == group.most else f"{group.least} to {group.most}"
    choices = ", ".join(f"{c.id} +{format_naira(c.delta_kobo)}" for c in group.choices)
    return f"{group.id} (choose {count}): {choices}"


def _options(offer: Offer) -> str:
    return f" | options {'; '.join(map(_group, offer.option_groups))}" if offer.option_groups else ""


def offer_line(offer: Offer, merchant: Merchant) -> str:
    if not offer.available:
        return f"{offer.id} | {offer.name} | sold out"
    amount = " | name the amount as amount_kobo" if offer.price_kind in ("range", "open") else ""
    return f"{offer.id} | {offer.name} | {_price(offer, merchant)}{amount}{_options(offer)}"


def _asks(merchant: Merchant) -> str:
    fields = [
        f"{f.name}{'' if f.required else ' (optional)'} = {f.label}"
        + (f", one of {', '.join(f.options)}" if f.options else "")
        for f in merchant.fields
    ]
    named = ", ".join(f.name for f in merchant.check_fields)
    checks = (
        f" It checks the account first: call check_account with {named}, then pass its check_id."
        if merchant.checks_account
        else ""
    )
    return f"Fields for create_quote: {'; '.join(fields) or 'none'}.{checks}"


def offer_listing(merchant: Merchant, offers: list[Offer], unmatched: str | None = None) -> str:
    shown = offers[:SHOWN_OFFERS]
    more = len(offers) - len(shown)
    fee = f" {merchant.fee_label}: {format_naira(merchant.fee_kobo)}." if merchant.fee_kobo else ""
    head = (
        f"{merchant.name} ({status_words(merchant)}). Orders of {_limits(merchant)}.{fee} {_asks(merchant)}"
    )
    tail = [f"{more} more: narrow with a query."] if more > 0 else []
    none = [NONE_MATCH.format(query=unmatched)] if unmatched else []
    lines = [NOTICE, *none, head, "id | name | price", *(offer_line(o, merchant) for o in shown), *tail]
    return "\n".join([*lines, CHECKED_NEXT if merchant.checks_account else BUY_NEXT])
