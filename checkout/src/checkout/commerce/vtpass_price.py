# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pricing a television or electricity order (docs/commerce.md, rule 1). A bouquet costs what VTpass lists it
at; a renewal costs the renewal amount of the account check; electricity costs the amount the person named,
within the least and most the meter's check returned. The model's lines carry an offer id and, for
electricity, an amount, and nothing else about money. The check's facts (the address, the bouquet now, the
arrears) are kept on the quote as fields, so the card shows them and the approval is bound to them."""

from collections.abc import Mapping

from ..errors import DomainError
from ..money import Kobo, format_naira
from ..vtpass.bills import RENEWABLE, SERVICES
from ..vtpass.phone import normalise_phone
from .model import AccountCheck, Basket, Fee, Merchant, Offer, PricedLine, Totals
from .pricing import assert_order_within_limits, price_lines
from .vtpass_check import ACCOUNT_FIELD, METER_TYPE

SERVICE_FEE = "Service fee"
CARD_FACTS = ("Address", "Status", "Current bouquet", "Due date", "Arrears")
"""The check's facts that the approval card shows beside the holder; the rest are in the tool's reply."""
MONTHS = 1
"""A DStv or GOtv subscription is paid for one month at a time."""


def _renewal(offer: Offer, check: AccountCheck | None) -> PricedLine:
    renewal = (check.detail if check else {}).get("renewal_kobo")
    if not renewal:
        raise DomainError(
            "RENEWAL_UNKNOWN",
            "VTpass did not give the renewal amount for this card, so it cannot be renewed as it is. "
            "Show the person the bouquets (find_items) and have them pick one to change to.",
        )
    bouquet = check.detail.get("bouquet") if check else None
    return PricedLine(offer.id, f"Renew {bouquet}" if bouquet else offer.name, 1, renewal)


def _lines(merchant: Merchant, offers: Mapping[str, Offer], basket: Basket, check: AccountCheck | None):
    chosen = offers.get(basket.lines[0].offer_id)
    if chosen is not None and chosen.price_kind == "renewal":
        if basket.amount_kobo is not None:
            raise DomainError(
                "AMOUNT_NOT_ACCEPTED", "A renewal costs the renewal amount VTpass gave; pass no amount."
            )
        return (_renewal(chosen, check),)
    lines = price_lines(merchant, offers, basket)
    if merchant.id in RENEWABLE:
        return tuple(PricedLine(x.offer_id, f"Change to {x.name}", x.quantity, x.unit_kobo) for x in lines)
    return lines


def _assert_within_check(merchant: Merchant, check: AccountCheck | None, amount: Kobo) -> None:
    """A meter's own least and most, from its account check; never a figure of ours."""
    least = (check.detail if check else {}).get("min_kobo")
    most = (check.detail if check else {}).get("max_kobo")
    if (least and amount < least) or (most and amount > most):
        bounds = " and ".join(
            part
            for part in (
                f"at least {format_naira(least)}" if least else "",
                f"at most {format_naira(most)}" if most else "",
            )
            if part
        )
        raise DomainError(
            "AMOUNT_OUT_OF_LIMITS",
            f"{merchant.name} takes {bounds} for this meter; {format_naira(amount)} is outside it. Nothing "
            "was quoted. Ask the person for an amount within it.",
        )


def _order(merchant: Merchant, basket: Basket, check: AccountCheck | None, offer: Offer, phone: str) -> dict:
    kind = SERVICES[merchant.id][0]
    account = check.fields if check else {}
    renews = offer.price_kind == "renewal"
    subscription = ("renew" if renews else "change") if merchant.id in RENEWABLE else None
    return {
        "service": merchant.id,
        "billers_code": account.get(ACCOUNT_FIELD[kind], phone),
        "phone": phone,
        "variation": None if renews or kind == "electricity" else offer.id,
        "subscription": subscription,
        "meter_type": account.get(METER_TYPE),
        "months": MONTHS if merchant.id in RENEWABLE else None,
    }


def _fields(merchant: Merchant, basket: Basket, check: AccountCheck | None, phone: str):
    given = {**basket.fields, "phone": phone}
    shown = tuple((s.name, s.label, given[s.name]) for s in merchant.fields if s.name in given)
    facts = tuple(
        (label.lower().replace(" ", "_"), label, value)
        for label, value in (check.detail if check else {}).get("facts", [])
        if label in CARD_FACTS
    )
    return shown + facts


def price_bill(
    merchant: Merchant,
    offers: Mapping[str, Offer],
    basket: Basket,
    check: AccountCheck | None,
    fee_kobo: Kobo,
) -> Totals:
    """The totals of one subscription or purchase, or why VTpass's merchant cannot take it."""
    if merchant.checks_account != (check is not None):
        raise DomainError(
            "ACCOUNT_CHECK_REQUIRED", f"{merchant.name} needs an account check; call check_account first."
        )
    if len(basket.lines) != 1:
        raise DomainError("INVALID_INPUT", f"{merchant.name} takes one subscription or purchase per quote.")
    phone = normalise_phone(basket.fields["phone"])
    lines = _lines(merchant, offers, basket, check)
    if SERVICES[merchant.id][0] == "electricity":
        _assert_within_check(merchant, check, lines[0].unit_kobo)
    fees = (Fee(SERVICE_FEE, fee_kobo),) if fee_kobo else ()
    offer = offers[basket.lines[0].offer_id]
    totals = Totals(
        lines,
        fees,
        _fields(merchant, basket, check, phone),
        check.holder_name if check else None,
        check.id if check else None,
        _order(merchant, basket, check, offer, phone),
    )
    assert_order_within_limits(merchant, totals.total_kobo)
    return totals
