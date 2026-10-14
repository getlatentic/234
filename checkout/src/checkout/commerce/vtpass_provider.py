# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `vtpass` provider (docs/commerce.md, "Providers"): television subscriptions and electricity, paid
through VTpass. Its merchants are rows (migrations/0022_commerce_bills.sql); what they sell is read from
VTpass (vtpass_offers.py), an account is checked by its `merchant-verify` (vtpass_check.py), and an order is
a `pay` with the request id fixed once per quote, asked about again with `requery`, never placed twice.

It is offered only while VTpass is simulated or in its sandbox, as every use of VTpass here is."""

from collections.abc import Mapping

from ..db import Db
from ..errors import DomainError
from ..ledger import Quote
from ..money import Kobo, format_naira
from ..vtpass.api import VtpassApi, VtpassOutcome
from ..vtpass.bills import BillOrder
from ..vtpass.request_id import request_id_at
from .directory_store import DirectoryStore
from .model import AccountCheck, Basket, Merchant, Offer, Outcome, Totals
from .provider import AccountLookup
from .vtpass_check import verify
from .vtpass_offers import vtpass_offers
from .vtpass_price import price_bill

NAME = "vtpass"
OFFERED_MODES = ("simulated", "sandbox")


def outcome_of(reply: VtpassOutcome) -> Outcome:
    """VTpass's answer as an order's outcome. A reversal is its own: a delivered order taken back."""
    status = "reversed" if reply.reversed else reply.status
    return Outcome(status, reply.description, reply.receipt, reply.unknown_request)


def order_of(quote: Quote) -> BillOrder:
    """The order to place for a quote, from what was priced and fixed with it."""
    wanted = quote.details["order"]
    return BillOrder(
        request_id=quote.progress["fulfilment"]["requestId"],
        service_id=wanted["service"],
        billers_code=wanted["billers_code"],
        phone=wanted["phone"],
        amount_kobo=quote.details["subtotalKobo"],
        variation_code=wanted["variation"],
        subscription_type=wanted["subscription"],
        meter_type=wanted["meter_type"],
        quantity=wanted["months"],
    )


class VtpassProvider:
    name = NAME

    def __init__(self, db: Db, api: VtpassApi, mode: str, service_fee_kobo: Kobo = 0) -> None:
        if mode not in OFFERED_MODES:
            raise ValueError(f"Bills are not offered with VTpass in mode {mode}.")
        self._store, self._api, self._fee = DirectoryStore(db, NAME), api, service_fee_kobo

    async def merchants(self, category: str | None = None) -> list[Merchant]:
        return await self._store.merchants(category)

    async def merchant(self, merchant_id: str) -> Merchant | None:
        return await self._store.merchant(merchant_id)

    async def offers(self, merchant: Merchant, query: str | None = None) -> list[Offer]:
        return await vtpass_offers(self._api, merchant, query)

    async def check(self, merchant: Merchant, fields: Mapping[str, str]) -> AccountLookup:
        if not merchant.checks_account:
            raise DomainError(
                "CHECK_NOT_NEEDED",
                f"{merchant.name} does not check accounts. Make the quote with its fields.",
            )
        return await verify(self._api, merchant, fields)

    async def price(self, merchant: Merchant, basket: Basket, check: AccountCheck | None) -> Totals:
        offers = {offer.id: offer for offer in await self.offers(merchant)}
        totals = price_bill(merchant, offers, basket, check, self._fee)
        await self._assert_deliverable(totals.subtotal_kobo)
        return totals

    async def _assert_deliverable(self, amount_kobo: Kobo) -> None:
        """Nobody is asked to pay for what VTpass will not deliver: its account must be accepted and its
        wallet must cover the order."""
        access = await self._api.check_access()
        if not access.ok:
            raise DomainError(
                "PROVIDER_ERROR",
                f"{access.reason} Bills cannot be delivered, so nothing was quoted. The owner should "
                "check the VTpass credentials.",
            )
        if access.balance_kobo is not None and access.balance_kobo < amount_kobo:
            raise DomainError(
                "PROVIDER_ERROR",
                f"The VTpass wallet holds less than {format_naira(amount_kobo)}, so nothing was quoted.",
            )

    def request_id(self, quote: Quote, now: int) -> str:
        return request_id_at(now, quote.id)

    async def fulfil(self, quote: Quote) -> Outcome:
        return outcome_of(await self._api.buy_bill(order_of(quote)))

    async def status(self, quote: Quote) -> Outcome:
        return outcome_of(await self._api.requery(quote.progress["fulfilment"]["requestId"]))


def bill_providers(
    db: Db, api: VtpassApi, mode: str, service_fee_kobo: Kobo = 0
) -> tuple[VtpassProvider, ...]:
    """The bills provider, only while VTpass is simulated or in its sandbox: with any other mode there are no
    television or electricity merchants to list or quote."""
    return (VtpassProvider(db, api, mode, service_fee_kobo),) if mode in OFFERED_MODES else ()
