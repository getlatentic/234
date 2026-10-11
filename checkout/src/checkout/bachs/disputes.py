# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bachs' dispute events, `dispute.created` and `dispute.updated`, read from a verified body (docs.bachs.io,
webhook events; a card payment's chargeback, signed and delivered as `collection.succeeded` is):

    {"id": "evt_…", "type": "dispute.created", "created_at": "…",
     "data": {"dispute_id": "dsp_…", "charge_id": "ch_…", "amount": "75000.00", "currency": "NGN",
              "status": "needs_response", "reason": "…", "response_deadline_at": "…", …}}

Either can come first and either can come more than once, so each carries the whole dispute as it stands and
234 acts on the status alone, not on the event's type (wallet/disputes.py). Fields are taken as they are: an
amount in another shape reads as None."""

from dataclasses import dataclass

from ..money import Kobo
from .api import kobo_of
from .events import event_of, object_of, text_of

DISPUTE_EVENTS = ("dispute.created", "dispute.updated")
KEPT_BY_234 = frozenset({"won", "closed"})
"""Bachs gives the set-aside money back to 234: on a ruling for 234, or when the dispute closes unruled."""
LOST_BY_234 = frozenset({"lost", "prevented"})
"""The customer has the money: by a ruling, or refunded before one."""


@dataclass(frozen=True)
class Dispute:
    event_id: str | None
    dispute_id: str | None
    charge_id: str | None
    amount_kobo: Kobo | None
    currency: str | None
    status: str | None

    @property
    def decision(self) -> str | None:
        """The final status, or None while the dispute is open (or in a status 234 does not know)."""
        return self.status if self.status in KEPT_BY_234 | LOST_BY_234 else None


def dispute_of(raw: bytes) -> Dispute | None:
    """The dispute a body announces, or None for a body that is not a dispute event."""
    event = event_of(raw, DISPUTE_EVENTS)
    if event is None:
        return None
    data = object_of(event.get("data"))
    return Dispute(
        event_id=text_of(event.get("id")),
        dispute_id=text_of(data.get("dispute_id")),
        charge_id=text_of(data.get("charge_id")),
        amount_kobo=kobo_of(data.get("amount")),
        currency=text_of(data.get("currency")),
        status=text_of(data.get("status")),
    )
