# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `directory` provider: merchants 234 onboards, listed in D1 (migrations/0020_commerce.sql). It prices a
basket from their offers and is the only place that does for them (commerce/pricing.py). Fulfilment, for now,
is the simulated merchants' (simulated.py): an order is a message to the merchant and its answer."""

from collections.abc import Mapping

from ..clock import Clock
from ..db import Db
from ..errors import DomainError
from ..ledger import Quote
from .directory_store import DirectoryStore
from .model import AccountCheck, Basket, Fee, Merchant, Offer, Outcome, Totals
from .pricing import assert_order_within_limits, merged, price_lines
from .provider import AccountLookup
from .simulated import ANSWERS, SimMerchants

NAME = "directory"


class DirectoryProvider:
    name = NAME

    def __init__(self, db: Db, clock: Clock) -> None:
        self._store = DirectoryStore(db, NAME)
        self._sim = SimMerchants(db, clock)

    async def merchants(self, category: str | None = None) -> list[Merchant]:
        return await self._store.merchants(category)

    async def merchant(self, merchant_id: str) -> Merchant | None:
        return await self._store.merchant(merchant_id)

    async def offers(self, merchant: Merchant, query: str | None = None) -> list[Offer]:
        return await self._store.offers(merchant.id, query)

    async def check(self, merchant: Merchant, fields: Mapping[str, str]) -> AccountLookup:
        """The merchant's first field names the account; the simulated merchants know a few."""
        if not merchant.checks_account:
            raise DomainError(
                "CHECK_NOT_NEEDED",
                f"{merchant.name} does not check accounts. Make the quote with its fields.",
            )
        reference = fields[merchant.fields[0].name]
        found = await self._sim.account(merchant.id, reference)
        if found is None:
            raise DomainError(
                "ACCOUNT_NOT_FOUND",
                f"{merchant.name} has no account {reference}. Ask the person to check the number.",
            )
        return found

    async def price(self, merchant: Merchant, basket: Basket, check: AccountCheck | None) -> Totals:
        if merchant.checks_account != (check is not None):
            raise DomainError(
                "ACCOUNT_CHECK_REQUIRED", f"{merchant.name} needs an account check; call check_account first."
            )
        offers = await self._store.offers_named(merchant.id, [line.offer_id for line in merged(basket.lines)])
        lines = price_lines(merchant, offers, basket)
        fees = (Fee(merchant.fee_label, merchant.fee_kobo),) if merchant.fee_kobo else ()
        labelled = tuple(
            (spec.name, spec.label, basket.fields[spec.name])
            for spec in merchant.fields
            if spec.name in basket.fields
        )
        totals = Totals(
            lines, fees, labelled, check.holder_name if check else None, check.id if check else None
        )
        assert_order_within_limits(merchant, totals.total_kobo)
        return totals

    def request_id(self, quote: Quote, now: int) -> str:
        return f"mrq-{quote.id}"

    async def fulfil(self, quote: Quote) -> Outcome:
        return await self._sim.place(quote.id)

    async def status(self, quote: Quote) -> Outcome:
        return await self._sim.outcome(quote.id) or Outcome("pending", ANSWERS["pending"])
