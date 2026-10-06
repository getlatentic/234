# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paystack's webhook: `x-paystack-signature` is the HMAC-SHA512, in hex, of the raw body with the secret key
(https://paystack.com/docs/payments/webhooks). In simulated mode there is no Paystack key, and the simulator
signs with a key derived from the approval secret, so the same check runs."""

import hashlib
import hmac
import json

from .references import quote_id_in

SIGNATURE_HEADER = "x-paystack-signature"
EVENTS = ("charge.success", "transfer.success", "transfer.failed", "transfer.reversed")


def simulated_key(approval_secret: str) -> str:
    return hmac.new(approval_secret.encode(), b"paystack-simulated-webhook", hashlib.sha256).hexdigest()


def sign(body: bytes, key: str) -> str:
    return hmac.new(key.encode(), body, hashlib.sha512).hexdigest()


def is_genuine(body: bytes, signature: str, key: str) -> bool:
    return bool(signature) and hmac.compare_digest(sign(body, key), signature)


def quote_of(body: bytes) -> str | None:
    """The quote a webhook is about, or None for an event this app does not act on."""
    try:
        event = json.loads(body)
    except ValueError:
        return None
    if not isinstance(event, dict) or event.get("event") not in EVENTS:
        return None
    data = event.get("data")
    return quote_id_in(data.get("reference")) if isinstance(data, dict) else None
