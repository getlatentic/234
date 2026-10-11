# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paystack's webhook: `x-paystack-signature` is the HMAC-SHA512, in hex, of the raw body with the secret key
(https://paystack.com/docs/payments/webhooks). In simulated mode there is no Paystack key, and the simulator
signs with a key derived from the approval secret, so the same check runs.

A refund event names the refunded payment by `data.transaction_reference`, and the refund itself by no id
234 keeps (https://paystack.com/docs/payments/refunds/), so it is a hint to ask about the quote's refund."""

import hashlib
import hmac
import json

from .references import quote_id_in, withdrawal_id_in

SIGNATURE_HEADER = "x-paystack-signature"
EVENTS = ("charge.success", "transfer.success", "transfer.failed", "transfer.reversed")
REFUND_EVENTS = (
    "refund.pending",
    "refund.processing",
    "refund.needs-attention",
    "refund.failed",
    "refund.processed",
)


def simulated_key(approval_secret: str) -> str:
    return hmac.new(approval_secret.encode(), b"paystack-simulated-webhook", hashlib.sha256).hexdigest()


def sign(body: bytes, key: str) -> str:
    return hmac.new(key.encode(), body, hashlib.sha512).hexdigest()


def is_genuine(body: bytes, signature: str, key: str) -> bool:
    return bool(signature) and hmac.compare_digest(sign(body, key), signature)


def _data_of(body: bytes, events: tuple[str, ...]) -> dict | None:
    try:
        event = json.loads(body)
    except ValueError:
        return None
    if not isinstance(event, dict) or event.get("event") not in events:
        return None
    data = event.get("data")
    return data if isinstance(data, dict) else None


def quote_of(body: bytes) -> str | None:
    """The quote or wallet withdrawal a webhook is about, or None for an event this app does not act on."""
    reference = (_data_of(body, EVENTS) or {}).get("reference")
    return withdrawal_id_in(reference) or quote_id_in(reference)


def refund_of(body: bytes) -> str | None:
    """The quote whose payment a refund event is about, or None when it is not a refund event."""
    return quote_id_in((_data_of(body, REFUND_EVENTS) or {}).get("transaction_reference"))
