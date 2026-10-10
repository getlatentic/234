# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one Bachs event a top-up acts on, `collection.succeeded`, read from a verified body
(https://docs.bachs.io/guides/webhooks/events/collection-succeeded):

    {"id": "evt_…", "type": "collection.succeeded", "created_at": "…",
     "data": {"checkout_id": "chk_…", "reference": "<ours>", "status": "SUCCEEDED",
              "amount": "75000.00", "currency": "NGN", "metadata": {…}, …}}

Fields are taken as they are, never coerced: an amount in another shape reads as None, and the top-up it names
is then credited nothing (wallet/topup_credit.py)."""

import json
from dataclasses import dataclass
from typing import Any

from ..money import Kobo
from .api import kobo_of

COLLECTION_SUCCEEDED = "collection.succeeded"
OWNER_TAG = "wallet_owner"


@dataclass(frozen=True)
class Collection:
    event_id: str | None
    reference: str | None
    checkout_id: str | None
    status: str | None
    amount_kobo: Kobo | None
    currency: str | None
    owner_tag: str | None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def collection_of(raw: bytes) -> Collection | None:
    """The collection a body announces, or None for a body that is not a `collection.succeeded` event."""
    try:
        event = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(event, dict) or event.get("type") != COLLECTION_SUCCEEDED:
        return None
    data = _object(event.get("data"))
    return Collection(
        event_id=_text(event.get("id")),
        reference=_text(data.get("reference")),
        checkout_id=_text(data.get("checkout_id")),
        status=_text(data.get("status")),
        amount_kobo=kobo_of(data.get("amount")),
        currency=_text(data.get("currency")),
        owner_tag=_text(_object(data.get("metadata")).get(OWNER_TAG)),
    )
