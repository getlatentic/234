# SPDX-License-Identifier: AGPL-3.0-or-later
"""The real Paystack client: the documented REST calls, over any `Transport`. It refuses a key that
is not a test key, so no code path here can move real money."""

import json
from typing import Any, Literal
from urllib.parse import quote, urlencode

from pydantic import BaseModel, ConfigDict, ValidationError

from ..transport import Transport, TransportError
from .api import (
    PAYSTACK_API_URL,
    TRANSACTION_STATUSES,
    TRANSFER_STATUSES,
    AccountLookup,
    Checkout,
    CheckoutRequest,
    PaystackError,
    Recipient,
    RecipientRequest,
    TransactionCheck,
    TransferOutcome,
    TransferRequest,
)

DEFAULT_TIMEOUT_SECONDS = 15.0


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class _Envelope(_Model):
    status: bool
    message: str | None = None
    data: Any = None


class _CheckoutData(_Model):
    authorization_url: str
    access_code: str
    reference: str


class _TransactionData(_Model):
    status: Literal[*TRANSACTION_STATUSES]
    reference: str
    amount: int
    currency: str
    gateway_response: str | None = None
    paid_at: str | None = None


class _AccountData(_Model):
    account_name: str


class _RecipientDetails(_Model):
    bank_name: str | None = None


class _RecipientData(_Model):
    recipient_code: str
    name: str
    details: _RecipientDetails | None = None


class _TransferData(_Model):
    status: Literal[*TRANSFER_STATUSES]
    transfer_code: str
    reference: str
    amount: int


class PaystackClient:
    def __init__(
        self,
        secret_key: str,
        transport: Transport,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        base_url: str = PAYSTACK_API_URL,
    ) -> None:
        if not secret_key.startswith("sk_test_"):
            raise ValueError("PaystackClient only accepts a test secret key (sk_test_...).")
        self._secret_key = secret_key
        self._transport = transport
        self._timeout = timeout_seconds
        self._base_url = base_url

    async def _call[T: BaseModel](
        self, method: str, path: str, model: type[T], body: dict[str, Any] | None = None
    ) -> T:
        try:
            reply = await self._transport.send(
                method,
                f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {self._secret_key}", "Content-Type": "application/json"},
                body=None if body is None else json.dumps(body),
                timeout_seconds=self._timeout,
            )
        except TransportError as error:
            raise PaystackError("Paystack could not be reached.", retryable=True) from error
        envelope = _envelope_of(reply.body)
        if not reply.ok or envelope is None or not envelope.status:
            message = (
                "Paystack sent a reply this client could not read."
                if envelope is None
                else envelope.message or "Paystack refused the request."
            )
            raise PaystackError(message, reply.status >= 500 or reply.status == 429, reply.status)
        try:
            return model.model_validate(envelope.data)
        except ValidationError as error:
            raise PaystackError(
                "Paystack's reply did not have the expected shape.", False, reply.status
            ) from error

    async def initialize_transaction(self, request: CheckoutRequest) -> Checkout:
        metadata = {
            "quote_id": request.quote_id,
            "custom_fields": [{"display_name": "For", "variable_name": "for", "value": request.description}],
        }
        data = await self._call(
            "POST",
            "/transaction/initialize",
            _CheckoutData,
            {
                "email": request.email,
                "amount": str(request.amount_kobo),
                "currency": "NGN",
                "reference": request.reference,
                "metadata": json.dumps(metadata),
            },
        )
        return Checkout(data.authorization_url, data.access_code, data.reference)

    async def verify_transaction(self, reference: str) -> TransactionCheck:
        data = await self._call("GET", f"/transaction/verify/{quote(reference, safe='')}", _TransactionData)
        return TransactionCheck(
            data.status, data.reference, data.amount, data.currency, data.gateway_response, data.paid_at
        )

    async def resolve_account(self, lookup: AccountLookup) -> str:
        query = urlencode({"account_number": lookup.account_number, "bank_code": lookup.bank_code})
        return (await self._call("GET", f"/bank/resolve?{query}", _AccountData)).account_name

    async def create_recipient(self, request: RecipientRequest) -> Recipient:
        data = await self._call(
            "POST",
            "/transferrecipient",
            _RecipientData,
            {
                "type": "nuban",
                "name": request.name,
                "account_number": request.account_number,
                "bank_code": request.bank_code,
                "currency": "NGN",
            },
        )
        bank = data.details.bank_name if data.details and data.details.bank_name else "Unknown bank"
        return Recipient(data.recipient_code, data.name, bank)

    @staticmethod
    def _transfer(data: _TransferData) -> TransferOutcome:
        return TransferOutcome(data.status, data.transfer_code, data.reference, data.amount)

    async def initiate_transfer(self, request: TransferRequest) -> TransferOutcome:
        data = await self._call(
            "POST",
            "/transfer",
            _TransferData,
            {
                "source": "balance",
                "amount": request.amount_kobo,
                "recipient": request.recipient_code,
                "reference": request.reference,
                "reason": request.reason,
            },
        )
        return self._transfer(data)

    async def finalize_transfer(self, transfer_code: str, otp: str) -> TransferOutcome:
        data = await self._call(
            "POST", "/transfer/finalize_transfer", _TransferData, {"transfer_code": transfer_code, "otp": otp}
        )
        return self._transfer(data)

    async def verify_transfer(self, reference: str) -> TransferOutcome:
        return self._transfer(
            await self._call("GET", f"/transfer/verify/{quote(reference, safe='')}", _TransferData)
        )


def _envelope_of(text: str) -> _Envelope | None:
    try:
        return _Envelope.model_validate(json.loads(text))
    except ValueError, ValidationError:
        return None
