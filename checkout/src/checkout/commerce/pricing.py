# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pricing a basket from the offers alone (docs/commerce.md, rule 1). The model's lines carry an offer id, a
count and option ids; the price of a line is the offer's, plus its chosen options', and the one amount the
model may name is for a single `open` or `range` offer, within its limits. Integer kobo throughout."""

from collections.abc import Mapping

from ..errors import DomainError
from ..money import Kobo, format_naira
from .model import MAX_LINES, MAX_QUANTITY, Basket, BasketLine, Merchant, Offer, PricedLine
from .options import chosen


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_QUANTITY


def merged(lines: tuple[BasketLine, ...]) -> tuple[BasketLine, ...]:
    """The same offer with the same options is one line; the lines are 1 to MAX_LINES."""
    counts: dict[tuple[str, tuple[str, ...]], int] = {}
    for line in lines:
        if not _is_count(line.quantity):
            raise DomainError("INVALID_INPUT", f"Quantity must be a whole number from 1 to {MAX_QUANTITY}.")
        key = (line.offer_id, tuple(sorted(line.options)))
        counts[key] = counts.get(key, 0) + line.quantity
    if not counts or len(counts) > MAX_LINES:
        raise DomainError("INVALID_INPUT", f"A basket has 1 to {MAX_LINES} different items.")
    return tuple(BasketLine(offer_id, count, options) for (offer_id, options), count in counts.items())


def _offer(merchant: Merchant, offers: Mapping[str, Offer], offer_id: str) -> Offer:
    offer = offers.get(offer_id)
    if offer is None:
        raise DomainError(
            "OFFER_NOT_FOUND",
            f'{merchant.name} has no offer "{offer_id}". find_items lists what it sells; '
            "pass an offer_id from it.",
        )
    if not offer.available:
        raise DomainError("ITEM_UNAVAILABLE", f"{offer.name} is not available. Pick another offer.")
    return offer


def _open_amount(merchant: Merchant, offer: Offer, amount: Kobo | None) -> Kobo:
    """The amount for an open or range offer, which only the person names, within its limits."""
    if amount is None:
        raise DomainError(
            "AMOUNT_REQUIRED",
            f"{offer.name} takes an amount. Ask the person how much, then pass amount_kobo.",
        )
    least, most = (
        (offer.min_kobo, offer.max_kobo)
        if offer.price_kind == "range"
        else (merchant.min_kobo, merchant.max_kobo)
    )
    if least is None or most is None or not least <= amount <= most:
        raise DomainError(
            "AMOUNT_OUT_OF_LIMITS",
            f"{offer.name} takes {format_naira(least or 0)} to {format_naira(most or 0)}; "
            f"{format_naira(amount)} is outside it. Nothing was quoted. Ask the person for an amount "
            "within it.",
        )
    return amount


def _priced(merchant: Merchant, offer: Offer, line: BasketLine, amount: Kobo | None) -> PricedLine:
    if line.quantity > offer.max_quantity:
        raise DomainError("INVALID_INPUT", f"At most {offer.max_quantity} of {offer.name}.")
    picked = chosen(offer, line.options)
    if offer.price_kind == "fixed":
        unit = (offer.price_kobo or 0) + sum(choice.delta_kobo for choice in picked)
    else:
        if line.quantity != 1:
            raise DomainError("INVALID_INPUT", f"{offer.name} is paid once, for an amount.")
        unit = _open_amount(merchant, offer, amount)
    return PricedLine(offer.id, offer.name, line.quantity, unit, tuple(choice.label for choice in picked))


def price_lines(merchant: Merchant, offers: Mapping[str, Offer], basket: Basket) -> tuple[PricedLine, ...]:
    """Each line at the offer's price. An open or range offer stands alone in its basket, and an amount
    is taken for it alone."""
    lines = merged(basket.lines)
    named = [_offer(merchant, offers, line.offer_id) for line in lines]
    priced_by_amount = [offer for offer in named if offer.price_kind != "fixed"]
    if priced_by_amount and len(lines) > 1:
        raise DomainError(
            "INVALID_INPUT",
            f"{priced_by_amount[0].name} is paid for an amount on its own; make it a quote by itself.",
        )
    if basket.amount_kobo is not None and not priced_by_amount:
        raise DomainError(
            "AMOUNT_NOT_ACCEPTED",
            "An amount is only for an offer with an open or ranged price. Pass the offers and quantities "
            "instead; the server prices them.",
        )
    return tuple(
        _priced(merchant, offer, line, basket.amount_kobo) for offer, line in zip(named, lines, strict=True)
    )


def assert_order_within_limits(merchant: Merchant, total: Kobo) -> None:
    """The merchant's least and most for one order, delivery and fees included."""
    if total < merchant.min_kobo:
        raise DomainError(
            "ORDER_OUT_OF_LIMITS",
            f"{merchant.name} takes orders of at least {format_naira(merchant.min_kobo)}; this one comes to "
            f"{format_naira(total)} with its fees. Add something, or ask the person for a larger amount.",
        )
    if total > merchant.max_kobo:
        raise DomainError(
            "ORDER_OUT_OF_LIMITS",
            f"{merchant.name} takes orders of at most {format_naira(merchant.max_kobo)}; this one comes to "
            f"{format_naira(total)} with its fees. Take something out, or ask for a smaller amount.",
        )
