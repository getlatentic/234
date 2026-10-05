# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standard Webhooks signatures: HMAC-SHA256 over `{id}.{timestamp}.{body}` with the key a subscriber gave
as `whsec_` and base64 (24 to 64 bytes), sent as `v1,<base64>`."""

import base64
import binascii
import hashlib
import hmac

PREFIX = "whsec_"
MIN_KEY, MAX_KEY = 24, 64


def key_of(secret: object) -> bytes:
    if not isinstance(secret, str) or not secret.startswith(PREFIX):
        raise ValueError("the secret must start with whsec_")
    try:
        key = base64.b64decode(secret.removeprefix(PREFIX), validate=True)
    except binascii.Error as error:
        raise ValueError("the secret is not base64") from error
    if not MIN_KEY <= len(key) <= MAX_KEY:
        raise ValueError("the secret must decode to 24 to 64 bytes")
    return key


def sign(secret: str, message_id: str, timestamp: int, body: str) -> str:
    signed = f"{message_id}.{timestamp}.{body}".encode()
    return "v1," + base64.b64encode(hmac.new(key_of(secret), signed, hashlib.sha256).digest()).decode()


def headers(secret: str, message_id: str, timestamp: int, body: str, subscription_id: str) -> dict[str, str]:
    return {
        "content-type": "application/json",
        "webhook-id": message_id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": sign(secret, message_id, timestamp, body),
        "x-mcp-subscription-id": subscription_id,
    }
