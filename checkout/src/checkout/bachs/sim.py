# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Bachs that answers from local state: the request the real client sends, the reply shapes of the docs, and
their documented rules (a sandbox key, `pricing` as a decimal string at the currency's precision, a reference
unique for good, an Idempotency-Key answered by the first reply or refused with another body). It is a
`Transport`, so the real client talks to it unchanged; its pay page is sim_page.py."""

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from ..clock import Clock
from ..transport import Reply
from .api import NGN, SANDBOX_KEY_PREFIX, kobo_of
from .sim_store import BachsSimStore, NewCheckout, SimCheckout

SIMULATED_KEY = f"{SANDBOX_KEY_PREFIX}simulated"
DEFAULT_MINUTES = 60
MAX_MINUTES = 1440
MAX_REFERENCE = 128
PATH = "/v1/checkout-sessions"


def simulated_webhook_secret(approval_secret: str) -> str:
    """The simulator's signing secret: there is no Bachs endpoint secret in simulated mode."""
    return hmac.new(approval_secret.encode(), b"bachs-simulated-webhook", hashlib.sha256).hexdigest()


def iso(at_ms: int) -> str:
    moment = datetime.fromtimestamp(at_ms / 1000, UTC)
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def fail(status: int, code: str, detail: str) -> Reply:
    return Reply(status, json.dumps({"detail": detail, "error_code": code}), "application/json")


def _created(checkout: SimCheckout, page_base: str, created_at: int) -> Reply:
    body = {
        "checkout_id": checkout.checkout_id,
        "checkout_url": f"{page_base}/{checkout.checkout_id}",
        "status": "open",
        "expires_at": iso(checkout.expires_at),
        "created_at": iso(created_at),
    }
    return Reply(201, json.dumps(body), "application/json")


def _invalid(body: dict[str, Any]) -> str | None:
    pricing = body.get("pricing")
    reference = body.get("reference")
    minutes = body.get("expires_in_minutes", DEFAULT_MINUTES)
    if not isinstance(pricing, dict) or pricing.get("currency") != NGN:
        return "pricing must name the NGN currency."
    if not (kobo_of(pricing.get("amount")) or 0) > 0:
        return "pricing.amount must be a positive decimal string at the currency's precision."
    if not isinstance(reference, str) or not 0 < len(reference) <= MAX_REFERENCE:
        return "reference must be text of at most 128 characters."
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= MAX_MINUTES:
        return "expires_in_minutes must be a whole number from 1 to 1440."
    if not isinstance(body.get("metadata", {}), dict) or not isinstance(body.get("customer", {}), dict):
        return "metadata and customer must be objects."
    return None


class BachsSimulator:
    def __init__(self, store: BachsSimStore, clock: Clock, page_base_url: str) -> None:
        self._store = store
        self._clock = clock
        self._page_base = page_base_url.rstrip("/")

    async def send(
        self, method: str, url: str, *, headers: Mapping[str, str], body: str | None, timeout_seconds: float
    ) -> Reply:
        del timeout_seconds
        given = {k.lower(): v for k, v in headers.items()}
        if not given.get("authorization", "").startswith(f"Bearer {SANDBOX_KEY_PREFIX}"):
            return fail(401, "UNAUTHORIZED", "Invalid API key")
        if method != "POST" or urlsplit(url).path != PATH:
            return fail(404, "NOT_FOUND", "Not found")
        return await self._create(given.get("idempotency-key"), body or "")

    async def _create(self, key: str | None, raw: str) -> Reply:
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        problem = _invalid(body) if isinstance(body, dict) else "The body must be a JSON object."
        if problem or not isinstance(body, dict):
            return fail(400, "VALIDATION_ERROR", problem or "The body must be a JSON object.")
        digest = hashlib.sha256(raw.encode()).hexdigest()
        if key and (earlier := await self._store.by_idempotency_key(key)):
            if earlier.request_hash != digest:
                return fail(409, "IDEMPOTENCY_CONFLICT", "This Idempotency-Key was used with another body.")
            return _created(earlier, self._page_base, self._clock.now())
        now = self._clock.now()
        minutes = body.get("expires_in_minutes", DEFAULT_MINUTES)
        made = await self._store.add(
            NewCheckout(
                body["reference"],
                key,
                digest,
                body["pricing"]["amount"],
                NGN,
                (body.get("customer") or {}).get("email"),
                body.get("metadata", {}),
                now,
                now + minutes * 60_000,
            )
        )
        if made is None:
            return fail(400, "VALIDATION_ERROR", "This reference was already used for a checkout.")
        return _created(made, self._page_base, now)
