# SPDX-License-Identifier: AGPL-3.0-or-later
"""The words of docs/commerce.md as values: a merchant, its offers, a basket, an account check and the totals
the server works out. Prices are integer kobo, and only a provider makes a `Totals`."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from ..money import Kobo

CATEGORIES: tuple[str, ...] = (
    "food",
    "grocery",
    "health",
    "shop",
    "service",
    "airtime",
    "data",
    "tv",
    "electricity",
)
QUOTABLE_STATUSES = ("live", "beta")
MAX_LINES = 12
MAX_QUANTITY = 10
NO_MAXIMUM_KOBO: Kobo = 10**13
"""A merchant's `max_kobo` when it states no most of its own; the person's limits still apply."""

PriceKind = Literal["fixed", "range", "open", "renewal"]
FieldKind = Literal["text", "digits", "choice"]
OutcomeStatus = Literal["delivered", "pending", "failed", "reversed"]


@dataclass(frozen=True)
class FieldSpec:
    """One thing the buyer must give a merchant: a delivery area, a customer number."""

    name: str
    label: str
    kind: FieldKind
    required: bool = True
    options: tuple[str, ...] = ()
    least: int = 1
    most: int = 120
    account: bool = False
    """Part of what names the account an account check looks up (a meter number, not a phone)."""


@dataclass(frozen=True)
class Merchant:
    id: str
    provider: str
    name: str
    category: str
    status: str
    requires_link: bool
    blurb: str
    min_kobo: Kobo
    max_kobo: Kobo
    fee_label: str
    fee_kobo: Kobo
    checks_account: bool
    fields: tuple[FieldSpec, ...]

    @property
    def quotable(self) -> bool:
        return self.status in QUOTABLE_STATUSES and not self.requires_link

    @property
    def check_fields(self) -> tuple[FieldSpec, ...]:
        """The fields an account check takes: those that name the account, else all of them."""
        return tuple(spec for spec in self.fields if spec.account) or self.fields

    @property
    def has_maximum(self) -> bool:
        return self.max_kobo < NO_MAXIMUM_KOBO


@dataclass(frozen=True)
class Choice:
    id: str
    label: str
    delta_kobo: Kobo = 0


@dataclass(frozen=True)
class OptionGroup:
    id: str
    label: str
    least: int
    most: int
    choices: tuple[Choice, ...]


@dataclass(frozen=True)
class Offer:
    merchant_id: str
    id: str
    name: str
    description: str
    tags: str
    price_kind: PriceKind
    price_kobo: Kobo | None
    min_kobo: Kobo | None
    max_kobo: Kobo | None
    available: bool
    max_quantity: int
    option_groups: tuple[OptionGroup, ...] = ()


@dataclass(frozen=True)
class BasketLine:
    """What the model sends for one line: an offer, how many, the options chosen, and nothing about money."""

    offer_id: str
    quantity: int = 1
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class Basket:
    """`amount_kobo` is the only money the model may name: for the one line of an `open` or `range` offer."""

    lines: tuple[BasketLine, ...]
    amount_kobo: Kobo | None = None
    fields: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountCheck:
    id: str
    merchant_id: str
    holder_name: str
    due_kobo: Kobo | None
    fields: Mapping[str, str]
    created_at: int
    expires_at: int
    detail: Mapping[str, Any] = field(default_factory=dict)
    """What the provider found beyond the holder: facts to show, and the limits and amounts it priced from."""


@dataclass(frozen=True)
class PricedLine:
    offer_id: str
    name: str
    quantity: int
    unit_kobo: Kobo
    options: tuple[str, ...] = ()

    @property
    def total_kobo(self) -> Kobo:
        return self.unit_kobo * self.quantity


@dataclass(frozen=True)
class Fee:
    label: str
    kobo: Kobo


@dataclass(frozen=True)
class Totals:
    """What a provider says an order costs. The quote stores all of it, and the card shows all of it."""

    lines: tuple[PricedLine, ...]
    fees: tuple[Fee, ...]
    fields: tuple[tuple[str, str, str], ...]
    """The buyer's fields as (name, label, value), in the merchant's order."""
    holder_name: str | None = None
    check_id: str | None = None
    order: Mapping[str, Any] = field(default_factory=dict)
    """What the provider needs to place the order later, fixed with the quote (a smartcard, a meter type)."""

    @property
    def subtotal_kobo(self) -> Kobo:
        return sum(line.total_kobo for line in self.lines)

    @property
    def total_kobo(self) -> Kobo:
        return self.subtotal_kobo + sum(fee.kobo for fee in self.fees)


@dataclass(frozen=True)
class Outcome:
    """Where a merchant's order stands. Anything that is not clearly delivered or failed is pending."""

    status: OutcomeStatus
    description: str
    receipt: tuple[tuple[str, str], ...] = ()
    """What a delivered order gives the buyer: a token, a voucher, the units."""
    unknown_request: bool = False
    """The provider says it never saw the request, so the order may be placed again."""
