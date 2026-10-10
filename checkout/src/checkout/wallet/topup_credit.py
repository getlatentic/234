# SPDX-License-Identifier: AGPL-3.0-or-later
"""A verified `collection.succeeded` becomes a `fund` entry (docs/wallet.md, "Funding").

The webhook only names a top-up; everything credited comes from 234's own row. A collection is credited only
when it matches that row exactly: the checkout 234 made for it, the owner it was made for, a full NGN
collection of exactly its amount. Anything else credits nothing and is audited.

The credit is the journal's, keyed by the top-up id, so a repeated or concurrent delivery finds the entry
the first one wrote and the cap is held in the same statement that writes it. The top-up is then marked paid
by one UPDATE that requires that entry, so a paid top-up always has its money in the wallet. A collection for
a top-up that expired is still credited: Bachs collected the money, and only crediting it keeps it the
payer's."""

from enum import StrEnum

from ..audit import Audit
from ..bachs.api import NGN
from ..bachs.events import Collection
from ..clock import Clock
from ..db import Db
from .topups import TopUp, TopUps, owner_tag

FULL_COLLECTION = "SUCCEEDED"

_MARK_PAID = (
    "UPDATE wallet_topup SET state = 'paid', paid_at = ? WHERE id = ? AND state <> 'paid' "
    "AND EXISTS (SELECT 1 FROM wallet_entry AS e WHERE e.owner = wallet_topup.owner AND e.kind = 'fund' "
    "AND e.ref = wallet_topup.id AND e.amount_kobo = wallet_topup.amount_kobo)"
)


class Outcome(StrEnum):
    CREDITED = "credited"
    UNKNOWN = "unknown"
    MISMATCH = "mismatch"
    OVER_CAP = "over_cap"


def mismatch(topup: TopUp, collection: Collection) -> str | None:
    """Why this collection does not pay this top-up, or None when it pays it exactly."""
    if topup.provider_ref is None or collection.checkout_id != topup.provider_ref:
        return "checkout"
    if collection.owner_tag != owner_tag(topup.owner):
        return "owner"
    if collection.status != FULL_COLLECTION:
        return "status"
    if collection.currency != NGN:
        return "currency"
    if collection.amount_kobo != topup.amount_kobo:
        return "amount"
    return None


class TopUpCredit:
    def __init__(self, topups: TopUps, db: Db, clock: Clock, audit: Audit) -> None:
        self._topups = topups
        self._db = db
        self._clock = clock
        self._audit = audit

    async def settle(self, collection: Collection) -> Outcome:
        topup = await self._topups.get(collection.reference) if collection.reference else None
        if topup is None:
            self._refused("unknown", collection)
            return Outcome.UNKNOWN
        problem = mismatch(topup, collection)
        if problem:
            self._refused(problem, collection, topup)
            return Outcome.MISMATCH
        entry = await self._topups.journal.credit(topup.owner, "fund", topup.amount_kobo, topup.id)
        if entry is None:
            self._audit.log(
                "wallet.topup.over_cap",
                topup=topup.id,
                amount_kobo=topup.amount_kobo,
                event_id=collection.event_id,
            )
            return Outcome.OVER_CAP
        marked = await self._db.execute(_MARK_PAID, self._clock.now(), topup.id)
        if marked == 1:
            self._audit.log(
                "wallet.topup.paid",
                topup=topup.id,
                amount_kobo=topup.amount_kobo,
                late=topup.state == "expired",
            )
        return Outcome.CREDITED

    def _refused(self, reason: str, collection: Collection, topup: TopUp | None = None) -> None:
        self._audit.log(
            "wallet.topup.refused",
            reason=reason,
            topup=topup.id if topup else None,
            reference=(collection.reference or "")[:64],
            checkout=collection.checkout_id,
            amount_kobo=collection.amount_kobo,
            expected_kobo=topup.amount_kobo if topup else None,
            event_id=collection.event_id,
        )
