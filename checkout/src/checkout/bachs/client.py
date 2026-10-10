# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Bachs client: the documented REST call 234 makes, over any `Transport`. It takes only a sandbox key, so
no code path here can reach live money.

POST /v1/checkout-sessions with `Authorization: Bearer <key>` and an `Idempotency-Key` header; the reply is
`{checkout_id, checkout_url, status, expires_at, created_at}`, and an error is `{detail, error_code}`
(https://docs.bachs.io/guides/checkout/checkout-sessions, /guides/idempotency, /errors)."""

import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, ValidationError

from ..transport import Reply, Transport, TransportError
from .api import SANDBOX_API_URL, SANDBOX_KEY_PREFIX, BachsError, Checkout, CheckoutRequest

DEFAULT_TIMEOUT_SECONDS = 15.0
IDEMPOTENCY_IN_PROGRESS = "IDEMPOTENCY_IN_PROGRESS"


class _CheckoutReply(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    checkout_id: str
    checkout_url: str
    status: str
    expires_at: str


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

    async def create_checkout(self, request: CheckoutRequest) -> Checkout:
        try:
            reply = await self._transport.send(
                "POST",
                f"{self._base_url}/v1/checkout-sessions",
                headers={
                    "Authorization": f"Bearer {self._secret_key}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": request.reference,
                },
                body=json.dumps(request.body()),
                timeout_seconds=self._timeout,
            )
        except TransportError as error:
            raise BachsError("Bachs could not be reached.", retryable=True) from error
        if not reply.ok:
            raise _error_of(reply)
        try:
            data = _CheckoutReply.model_validate_json(reply.body)
            return Checkout(data.checkout_id, data.checkout_url, data.status, epoch_ms(data.expires_at))
        except (ValidationError, ValueError) as error:
            raise BachsError("Bachs' reply did not have the expected shape.", False, reply.status) from error
