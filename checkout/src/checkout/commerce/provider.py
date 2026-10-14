# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a provider is (docs/commerce.md, "Providers"): the code that lists merchants, prices an order and
fulfils it. A new provider adds no tool, only an implementation of this and an entry in the registry.

Two things differ from the design's sketch. A provider's `check` returns what it found, the holder and what is
due; the core keeps that as an `AccountCheck` with an id (checks.py), so every provider's checks are held and
expire the same way. And `merchant` looks one up by id, which the registry needs to route a quote."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..ledger import Quote
from ..money import Kobo
from .model import AccountCheck, Basket, Merchant, Offer, Outcome, Totals


@dataclass(frozen=True)
class AccountLookup:
    """What a provider found for the account the buyer typed."""

    holder_name: str
    due_kobo: Kobo | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)
    """Facts to show (`facts`, label and value pairs) and what the provider priced from, as JSON values."""


class Provider(Protocol):
    name: str

    async def merchants(self, category: str | None = None) -> list[Merchant]: ...

    async def merchant(self, merchant_id: str) -> Merchant | None: ...

    async def offers(self, merchant: Merchant, query: str | None = None) -> list[Offer]: ...

    async def check(self, merchant: Merchant, fields: Mapping[str, str]) -> AccountLookup:
        """Looks the account up, or raises the refusal. It changes nothing."""
        ...

    async def price(self, merchant: Merchant, basket: Basket, check: AccountCheck | None) -> Totals:
        """The authoritative totals. Raises a refusal for a basket the merchant cannot take."""
        ...

    def request_id(self, quote: Quote, now: int) -> str:
        """The id the provider knows the order by, fixed once per quote."""
        ...

    async def fulfil(self, quote: Quote) -> Outcome:
        """Places the order of a paid quote under the request id in `quote.progress["fulfilment"]`.
        Idempotent by the quote: asked twice, it places one."""
        ...

    async def status(self, quote: Quote) -> Outcome:
        """Asks the provider where the order stands, without placing it again."""
        ...
