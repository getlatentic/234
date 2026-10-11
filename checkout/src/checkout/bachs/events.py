# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one Bachs event a top-up acts on, `collection.succeeded`, read from a verified body
(https://docs.bachs.io/guides/webhooks/events/collection-succeeded):

    {"id": "evt_…", "type": "collection.succeeded", "created_at": "…",
     "data": {"checkout_id": "chk_…", "charge_id": "ch_…", "reference": "<ours>", "status": "SUCCEEDED",
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
    charge_id: str | None
    """What a dispute names; the top-up keeps it once credited."""
    status: str | None
    amount_kobo: Kobo | None
    currency: str | None
    owner_tag: str | None


def text_of(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def object_of(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def event_of(raw: bytes, types: tuple[str, ...]) -> dict[str, Any] | None:
    """The event a body holds when it is one of these types, else None."""
    try:
        event = json.loads(raw)
    except ValueError:
        return None
    return event if isinstance(event, dict) and event.get("type") in types else None


def collection_of(raw: bytes) -> Collection | None:
    """The collection a body announces, or None for a body that is not a `collection.succeeded` event."""
    event = event_of(raw, (COLLECTION_SUCCEEDED,))
    if event is None:
        return None
    data = object_of(event.get("data"))
    return Collection(
        event_id=text_of(event.get("id")),
        reference=text_of(data.get("reference")),
        checkout_id=text_of(data.get("checkout_id")),
        charge_id=text_of(data.get("charge_id")),
        status=text_of(data.get("status")),
        amount_kobo=kobo_of(data.get("amount")),
        currency=text_of(data.get("currency")),
        owner_tag=text_of(object_of(data.get("metadata")).get(OWNER_TAG)),
    )
