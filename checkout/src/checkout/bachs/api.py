# SPDX-License-Identifier: AGPL-3.0-or-later
"""What 234 asks of Bachs and what comes back, free of how it travels (client.py, sim.py).

Bachs writes money as a decimal string at the currency's precision ("75000.00"), never in minor units
(https://docs.bachs.io/guides/checkout/checkout-sessions); 234 keeps integer kobo, and converts only here."""

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..money import KOBO_PER_NAIRA, Kobo

SANDBOX_API_URL = "https://sandbox-api.bachs.io"
NGN = "NGN"
SANDBOX_KEY_PREFIX = "sk_sandbox_"
LIVE_KEY_PREFIX = "sk_live_"

_NAIRA = re.compile(r"(?P<naira>0|[1-9]\d{0,12})\.(?P<kobo>\d{2})")


def naira_text(kobo: Kobo) -> str:
    naira, rest = divmod(kobo, KOBO_PER_NAIRA)
    return f"{naira}.{rest:02d}"


def kobo_of(text: object) -> Kobo | None:
    """The kobo in an NGN amount written as Bachs writes one, or None for any other shape."""
    found = _NAIRA.fullmatch(text) if isinstance(text, str) else None
    return int(found["naira"]) * KOBO_PER_NAIRA + int(found["kobo"]) if found else None


@dataclass(frozen=True)
class CheckoutRequest:
    reference: str
    """Unique per Bachs account for good; the Idempotency-Key too, so a retry finds the same checkout."""
    amount_kobo: Kobo
    expires_in_minutes: int
    metadata: dict[str, str] = field(default_factory=dict)
    customer_email: str | None = None
    success_url: str | None = None

    def body(self) -> dict[str, Any]:
        sent: dict[str, Any] = {
            "pricing": {"currency": NGN, "amount": naira_text(self.amount_kobo)},
            "reference": self.reference,
            "metadata": self.metadata,
            "expires_in_minutes": self.expires_in_minutes,
        }
        if self.customer_email:
            sent["customer"] = {"email": self.customer_email}
        if self.success_url:
            sent["success_url"] = self.success_url
        return sent


@dataclass(frozen=True)
class Checkout:
    checkout_id: str
    checkout_url: str
    status: str
    expires_at: int
    """Epoch milliseconds."""


class BachsError(Exception):
    """A failed call. `retryable` is true when the request may not have reached Bachs or may not have finished
    there; the same request, with the same Idempotency-Key, can then be sent again."""

    def __init__(self, message: str, retryable: bool = False, http_status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.http_status = http_status


class BachsApi(Protocol):
    async def create_checkout(self, request: CheckoutRequest) -> Checkout: ...
