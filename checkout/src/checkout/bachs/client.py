# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Bachs client: the documented REST call 234 makes, over any `Transport`. It takes only a sandbox key, so
no code path here can reach live money.

POST /v1/checkout-sessions with `Authorization: Bearer <key>` and an `Idempotency-Key` header; the reply is
`{checkout_id, checkout_url, status, expires_at, created_at}`, and an error is `{detail, error_code}`
(https://docs.bachs.io/guides/checkout/checkout-sessions, /guides/idempotency, /errors). GET /v1/balances
answers `{balances: [{currency, available_balance, pending_balance}]}`
(https://docs.bachs.io/connect/balances)."""

import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, ValidationError

from ..money import Kobo
from ..transport import Reply, Transport, TransportError
from .api import NGN, SANDBOX_API_URL, SANDBOX_KEY_PREFIX, BachsError, Checkout, CheckoutRequest, kobo_of

DEFAULT_TIMEOUT_SECONDS = 15.0
IDEMPOTENCY_IN_PROGRESS = "IDEMPOTENCY_IN_PROGRESS"


class _CheckoutReply(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    checkout_id: str
    checkout_url: str
    status: str
    expires_at: str


class _Balance(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    currency: str
    available_balance: str
    pending_balance: str


class _BalancesReply(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    balances: list[_Balance]


def signed_kobo_of(text: str) -> Kobo | None:
    """A balance, which a lost dispute can take below zero (https://docs.bachs.io/connect/balances)."""
    magnitude = kobo_of(text.removeprefix("-"))
    return None if magnitude is None else -magnitude if text.startswith("-") else magnitude


def epoch_ms(stamp: str) -> int:
    """Bachs' timestamps are ISO 8601 in UTC, with or without the offset written."""
    moment = datetime.fromisoformat(stamp)
    return int((moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp() * 1000)


def _error_of(reply: Reply) -> BachsError:
    try:
        parsed = json.loads(reply.body)
    except ValueError:
        parsed = None
    detail = parsed.get("detail") if isinstance(parsed, dict) else None
    code = parsed.get("error_code") if isinstance(parsed, dict) else None
    retryable = reply.status >= 500 or reply.status == 429 or code == IDEMPOTENCY_IN_PROGRESS
    message = detail if isinstance(detail, str) and detail else "Bachs refused the request."
    return BachsError(message, retryable, reply.status)


class BachsClient:
    def __init__(
        self,
        secret_key: str,
        transport: Transport,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        base_url: str = SANDBOX_API_URL,
    ) -> None:
        if not secret_key.startswith(SANDBOX_KEY_PREFIX):
            raise ValueError("BachsClient only accepts a sandbox secret key (sk_sandbox_...).")
        self._secret_key = secret_key
        self._transport = transport
        self._timeout = timeout_seconds
        self._base_url = base_url

    async def _send(self, method: str, path: str, headers: dict[str, str], body: str | None) -> Reply:
        try:
            reply = await self._transport.send(
                method,
                f"{self._base_url}{path}",
                headers={"Authorization": f"Bearer {self._secret_key}", **headers},
                body=body,
                timeout_seconds=self._timeout,
            )
        except TransportError as error:
            raise BachsError("Bachs could not be reached.", retryable=True) from error
        if not reply.ok:
            raise _error_of(reply)
        return reply

    async def create_checkout(self, request: CheckoutRequest) -> Checkout:
        reply = await self._send(
            "POST",
            "/v1/checkout-sessions",
            {"Content-Type": "application/json", "Idempotency-Key": request.reference},
            json.dumps(request.body()),
        )
        try:
            data = _CheckoutReply.model_validate_json(reply.body)
            return Checkout(data.checkout_id, data.checkout_url, data.status, epoch_ms(data.expires_at))
        except (ValidationError, ValueError) as error:
            raise BachsError("Bachs' reply did not have the expected shape.", False, reply.status) from error

    async def ngn_balance(self) -> Kobo:
        reply = await self._send("GET", "/v1/balances", {}, None)
        try:
            balances = _BalancesReply.model_validate_json(reply.body).balances
        except (ValidationError, ValueError) as error:
            raise BachsError("Bachs' reply did not have the expected shape.", False, reply.status) from error
        total = 0
        for balance in (b for b in balances if b.currency == NGN):
            available = signed_kobo_of(balance.available_balance)
            pending = signed_kobo_of(balance.pending_balance)
            if available is None or pending is None:
                raise BachsError("Bachs wrote an NGN balance 234 cannot read.", False, reply.status)
            total += available + pending
        return total
