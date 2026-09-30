# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telling the chat host that a simulated payment moved, so its open cards update at once instead of
waiting for their next poll.

The call is the host's signed `POST /hooks/payment` with the quote id. It is a courtesy: a host that
cannot be reached, refuses, or answers late changes nothing, because the card also polls, so every failure
is logged as one line and swallowed. The body carries the quote id and nothing else, and the only address
ever called is the configured one.
"""

import asyncio
import hashlib
import hmac
import json
from typing import Protocol

from .audit import Audit
from .config import PaymentWebhookSettings
from .transport import Transport

SIGNATURE_HEADER = "x-signature"
TIMEOUT_SECONDS = 4.0


def sign(body: str, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


class PaymentNotifier(Protocol):
    async def payment_moved(self, quote_id: str) -> None: ...


class NoNotifier:
    async def payment_moved(self, quote_id: str) -> None:
        del quote_id


class SignedWebhook:
    def __init__(
        self,
        settings: PaymentWebhookSettings,
        transport: Transport,
        audit: Audit,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._audit = audit
        self._timeout = timeout_seconds

    async def payment_moved(self, quote_id: str) -> None:
        body = json.dumps({"quote_id": quote_id}, separators=(",", ":"))
        headers = {
            "content-type": "application/json",
            SIGNATURE_HEADER: sign(body, self._settings.secret),
        }
        try:
            reply = await asyncio.wait_for(
                self._transport.send(
                    "POST", self._settings.url, headers=headers, body=body, timeout_seconds=self._timeout
                ),
                self._timeout,
            )
        except Exception as error:
            self._audit.log("webhook.failed", quote=quote_id, why=type(error).__name__)
            return
        self._audit.log(
            "webhook.sent" if reply.ok else "webhook.refused", quote=quote_id, status=reply.status
        )
