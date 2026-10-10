# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the ledger holds and hands out: a quote, the limits on spend, and the states that count as spent."""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from ..money import Kobo

SPENDING_STATES = ("approved", "settled", "refund_due")
ENDED_STATES = ("settled", "failed", "abandoned", "declined", "unavailable", "refund_due")
SPENDING_SQL = ", ".join(f"'{s}'" for s in SPENDING_STATES)


@dataclass(frozen=True)
class Limits:
    per_payment_kobo: Kobo
    daily_kobo: Kobo
    group_daily_kobo: Kobo = 50_000_000
    """What all the owners of one payer group may approve together in a day (owner.py)."""


@dataclass(frozen=True)
class ClaimTerms:
    """What a funding source adds to the one approval of a quote: progress written by the same UPDATE, and
    a condition on the quote row (`quotes`) that must hold in its WHERE."""

    progress: dict[str, Any]
    condition: str


@dataclass(frozen=True)
class Budget:
    per_payment_kobo: Kobo
    daily_kobo: Kobo
    spent_today_kobo: Kobo

    @property
    def remaining_today_kobo(self) -> Kobo:
        return max(self.daily_kobo - self.spent_today_kobo, 0)


@dataclass(frozen=True)
class CheckoutFacts:
    merchant: str
    description: str
    state: str


@dataclass(frozen=True)
class NewQuote:
    connector: str
    kind: str
    amount_kobo: Kobo
    description: str
    merchant: str
    merchant_ref: str | None
    details: dict[str, Any]
    idempotency_key: str
    request_hash: str


@dataclass(frozen=True)
class Quote:
    id: str
    connector: str
    kind: str
    amount_kobo: Kobo
    description: str
    merchant: str
    merchant_ref: str | None
    details: dict[str, Any]
    progress: dict[str, Any]
    state: str
    created_at: int
    expires_at: int
    approved_at: int | None
    settled_at: int | None
    request_hash: str = field(default="", repr=False)


def quote_of(row: dict[str, Any]) -> Quote:
    return Quote(
        id=row["id"],
        connector=row["connector"],
        kind=row["kind"],
        amount_kobo=row["amount_kobo"],
        description=row["description"],
        merchant=row["merchant"],
        merchant_ref=row["merchant_ref"],
        details=json.loads(row["details"]),
        progress=json.loads(row["progress"]),
        state=row["state"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        approved_at=row["approved_at"],
        settled_at=row["settled_at"],
        request_hash=row["request_hash"],
    )


def request_hash(**fields: Any) -> str:
    canonical = json.dumps(sorted(fields.items()), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
