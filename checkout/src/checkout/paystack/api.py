# SPDX-License-Identifier: AGPL-3.0-or-later
"""The slice of Paystack the connectors use. The real client and the simulator both speak it."""

import re
from dataclasses import dataclass
from typing import Protocol

from ..money import Kobo

PAYSTACK_API_URL = "https://api.paystack.co"

TRANSACTION_STATUSES = (
    "success",
    "failed",
    "abandoned",
    "ongoing",
    "pending",
    "processing",
    "queued",
    "reversed",
)
TRANSFER_STATUSES = ("pending", "otp", "success", "failed", "reversed")

# What Paystack says when the account is a Starter Business and cannot make payouts, even in test mode.
_PAYOUTS_UNAVAILABLE = re.compile(r"third[- ]party payouts|starter business", re.IGNORECASE)


class PaystackError(Exception):
    """A failed call. `retryable` is true when the request may not have reached Paystack or may not
    have finished there, so the same request can be sent again."""

    def __init__(self, message: str, retryable: bool = False, http_status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.http_status = http_status


def is_payouts_unavailable(error: Exception) -> bool:
    return isinstance(error, PaystackError) and bool(_PAYOUTS_UNAVAILABLE.search(str(error)))


@dataclass(frozen=True)
class CheckoutRequest:
    amount_kobo: Kobo
    email: str
    reference: str
    quote_id: str
    description: str


@dataclass(frozen=True)
class Checkout:
    authorization_url: str
    access_code: str
    reference: str


@dataclass(frozen=True)
class TransactionCheck:
    status: str
    reference: str
    amount_kobo: Kobo
    currency: str
    gateway_response: str | None
    paid_at: str | None


@dataclass(frozen=True)
class AccountLookup:
    account_number: str
    bank_code: str


@dataclass(frozen=True)
class RecipientRequest:
    name: str
    account_number: str
    bank_code: str


@dataclass(frozen=True)
class Recipient:
    recipient_code: str
    name: str
    bank_name: str


@dataclass(frozen=True)
class TransferRequest:
    amount_kobo: Kobo
    recipient_code: str
    reference: str
    reason: str


@dataclass(frozen=True)
class TransferOutcome:
    status: str
    transfer_code: str
    reference: str
    amount_kobo: Kobo


class PaystackApi(Protocol):
    async def initialize_transaction(self, request: CheckoutRequest) -> Checkout: ...

    async def verify_transaction(self, reference: str) -> TransactionCheck: ...

    async def resolve_account(self, lookup: AccountLookup) -> str:
        """The account holder's name, as the bank gives it."""
        ...

    async def create_recipient(self, request: RecipientRequest) -> Recipient: ...

    async def initiate_transfer(self, request: TransferRequest) -> TransferOutcome: ...

    async def finalize_transfer(self, transfer_code: str, otp: str) -> TransferOutcome: ...

    async def verify_transfer(self, reference: str) -> TransferOutcome: ...
