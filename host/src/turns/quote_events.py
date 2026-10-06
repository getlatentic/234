# SPDX-License-Identifier: AGPL-3.0-or-later
"""234's own chat hears how its quotes end the way any MCP client does: when a quote's card is recorded it
subscribes to `quote.finished` for that quote, as the chat's owner, and the connector sends the ending to
/hooks/events, signed with the key the host gave (Standard Webhooks). The card still polls; this makes the
ending reach the chat when nobody is looking at the card, and lets the model answer it at once."""

import base64
import hashlib
import hmac
from typing import Any

import httpx

from .hub import MEMORY_SERVER, Hub, HubError, ToolOutcome
from .settings import Settings

CALLBACK_PATH = "/hooks/events"
EVENT = "quote.finished"
TTL_MS = 24 * 3600 * 1000
TOLERANCE_SECONDS = 300
ENDED = {
    "settled": "paid and done",
    "failed": "failed, and nothing was charged",
    "abandoned": "abandoned at the checkout, and nothing was charged",
    "declined": "declined by the person",
    "unavailable": "not sent: the provider was not available",
    "refund_due": "owed a refund",
    "expired": "expired before it was approved",
}


def secret_of(events_secret: str) -> str:
    """The signing key the host gives each subscription, from its own EVENTS_SECRET."""
    digest = hmac.new(events_secret.encode(), b"234-mcp-events", hashlib.sha256).digest()
    return "whsec_" + base64.b64encode(digest).decode()


def subscription(quote_id: str, public_base_url: str, events_secret: str) -> dict[str, Any]:
    return {
        "name": EVENT,
        "arguments": {"quote_id": quote_id},
        "delivery": {
            "mode": "webhook",
            "url": public_base_url.rstrip("/") + CALLBACK_PATH,
            "secret": secret_of(events_secret),
        },
        "ttlMs": TTL_MS,
    }


def genuine(events_secret: str, headers: dict[str, str], body: bytes, now_s: float) -> bool:
    """Standard Webhooks: v1 signatures over `{id}.{timestamp}.{body}`, any of them matching, the timestamp
    within five minutes."""
    message_id, stamp = headers.get("webhook-id", ""), headers.get("webhook-timestamp", "")
    if not message_id or not stamp.isdigit() or abs(now_s - int(stamp)) > TOLERANCE_SECONDS:
        return False
    key = base64.b64decode(secret_of(events_secret).removeprefix("whsec_"))
    signed = hmac.new(key, f"{message_id}.{stamp}.".encode() + body, hashlib.sha256).digest()
    expected = "v1," + base64.b64encode(signed).decode()
    return any(hmac.compare_digest(given, expected) for given in headers.get("webhook-signature", "").split())


def told(data: dict[str, Any]) -> str:
    """What the model is told: the quote, what it was for, and how it ended."""
    amount = f"₦{int(data.get('amount_kobo', 0)) / 100:,.0f}"
    how = ENDED.get(str(data.get("state")), str(data.get("state")))
    return f"Quote {data.get('quote_id')} ({amount}, {data.get('description', '')}) {how}."


async def follow(hub: Hub, settings: Settings, outcome: ToolOutcome, owner: str) -> bool:
    """Subscribes to how the quote a card shows ends, as `owner` (a ledger owner key). A host without the
    settings, a card without a quote, or a connector that refuses leaves the card's own polling."""
    quote = (outcome.result.get("structuredContent") or {}).get("quote")
    if (
        not quote
        or outcome.server == MEMORY_SERVER
        or not (settings.events_secret and settings.public_base_url)
    ):
        return False
    params = subscription(quote["id"], settings.public_base_url, settings.events_secret)
    try:
        await hub.subscribe(outcome.server, params, owner)
    except HubError, httpx.HTTPError:
        return False
    return True
