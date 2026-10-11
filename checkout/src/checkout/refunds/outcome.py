# SPDX-License-Identifier: AGPL-3.0-or-later
"""What becomes of a quote's refund once it is opened (refunds/opening.py): the one send to Paystack's Refund
API (https://paystack.com/docs/api/refund/), and the outcome, followed until Paystack decides it.

* `processed` decides it, and a `refund_due` quote ends `refunded` in the same batch; a reversed quote stays
  reversed;
* `failed` decides it too, audited `refund.failed` for an operator: Paystack credits 234 back;
* `needs-attention` (Paystack wants the payer's bank account) and anything else leave it undecided, until a
  Paystack event or the minute asks again.

Paystack takes no idempotency key for a refund, so a refund is sent again only when 234 holds no Paystack
refund id for it, Paystack lists no refund of its transaction, no other caller is sending it, and a send whose
answer was lost is at least `SEND_STALE_MS` old. The quote's progress carries the refund's state, so the card
says where its money is."""

from collections.abc import Mapping

from ..audit import Audit
from ..clock import Clock
from ..db import Db
from ..paystack.api import PaystackApi, PaystackError, RefundOutcome, RefundRequest
from .opening import RefundOpening
from .owed import owed_sql
from .record import READ, UNDECIDED, UNDECIDED_SQL, Refund, refund_of

SEND_STALE_MS = 60_000
RECHECK_AFTER_MS = 30_000
RECHECK_LIMIT = 50
CUSTOMER_NOTE = "Refund from 234"

_SETTLE = (
    "UPDATE quote_refund SET state = ?, refund_id = COALESCE(?, refund_id), refund_status = ?, "
    "decided_at = ?, sending_since = NULL "
    f"WHERE quote_id = ? AND state IN ({UNDECIDED_SQL})"
)
_MIRROR = (
    "UPDATE quotes SET progress = json_patch(progress, json_object('refund', json_object('state', "
    "(SELECT r.state FROM quote_refund AS r WHERE r.quote_id = quotes.id)))) "
    "WHERE id = ? AND EXISTS (SELECT 1 FROM quote_refund AS r WHERE r.quote_id = quotes.id)"
)
_REFUNDED = (
    "UPDATE quotes SET state = 'refunded', settled_at = ? WHERE id = ? AND state = 'refund_due' "
    "AND EXISTS (SELECT 1 FROM quote_refund AS r WHERE r.quote_id = quotes.id AND r.state = 'processed')"
)
_TAKE_SEND = (
    "UPDATE quote_refund SET sending_since = ? WHERE quote_id = ? AND state = 'sent' "
    "AND refund_id IS NULL AND (sending_since IS NULL OR sending_since <= ?)"
)


def _ours(found: list[RefundOutcome]) -> RefundOutcome | None:
    """The refund Paystack holds for the transaction: one still standing before one that failed."""
    standing = [refund for refund in found if refund.status != "failed"]
    return (standing or found or [None])[0]


class RefundOutcomes:
    def __init__(self, db: Db, clock: Clock, paystack: Mapping[str, PaystackApi], audit: Audit) -> None:
        """`paystack` is each connector's Paystack: a refund goes through the one that took the payment."""
        self._db, self._clock, self._paystack, self._audit = db, clock, paystack, audit
        self.opening = RefundOpening(db, clock, audit)

    async def get(self, quote_id: str) -> Refund | None:
        """The one read that names no owner: a Paystack event names only the transaction."""
        row = await self._db.row(f"{READ}WHERE r.quote_id = ?", quote_id)
        return refund_of(row) if row else None

    async def follow(self, quote_id: str) -> Refund | None:
        """Opens and sends the refund a quote owes, or asks Paystack about the one it has."""
        refund = await self.get(quote_id)
        if refund is not None:
            return await self.recheck(refund)
        quote = await self.opening.owing(quote_id)
        if quote is None:
            return None
        opened = await self.opening.open(quote, self._paystack[quote.connector])
        refund = await self.get(quote_id)
        if opened.opened:
            await self._mirror(quote_id)
        if opened.sends and refund is not None:
            return await self.send(refund)
        return refund

    async def send(self, refund: Refund) -> Refund:
        """Sends a refund this caller took for sending: the whole amount, against the payment's reference."""
        notes = f"234 quote {refund.quote_id}"
        request = RefundRequest(refund.transaction_reference, refund.amount_kobo, notes, CUSTOMER_NOTE)
        try:
            outcome = await self._paystack[refund.connector].create_refund(request)
        except PaystackError as error:
            return await self._refused(refund, error)
        self._audit.log("refund.sent", quote=refund.quote_id, status=outcome.status)
        return await self.record(refund, outcome)

    async def _refused(self, refund: Refund, error: PaystackError) -> Refund:
        """A send that may not have reached Paystack stays undecided and keeps its claim. One Paystack refused
        is asked about once more, in case it already holds a refund of the transaction, before it fails."""
        if error.retryable:
            return await self._unanswered(refund)
        try:
            found = await self._find(refund)
        except PaystackError:
            return await self._unanswered(refund)
        if found is not None:
            return await self.record(refund, found)
        return await self._settle(refund, "failed", None, f"refused: {error}")

    async def _unanswered(self, refund: Refund) -> Refund:
        self._audit.log("refund.undecided", quote=refund.quote_id, why="no answer")
        return await self.get(refund.quote_id) or refund

    async def _find(self, refund: Refund) -> RefundOutcome | None:
        """Paystack's refund of this quote, or None when Paystack lists none for its transaction. Any call
        that did not answer raises: an unread answer is never taken for no refund."""
        paystack = self._paystack[refund.connector]
        if refund.refund_id is not None:
            return await paystack.fetch_refund(refund.refund_id)
        if refund.transaction_id is None:
            raise PaystackError("This refund names no transaction.")
        return _ours(await paystack.refunds_of(refund.transaction_id))

    async def record(self, refund: Refund, outcome: RefundOutcome) -> Refund:
        """What Paystack said, written only while the refund is undecided."""
        named = outcome.transaction_id
        if outcome.amount_kobo != refund.amount_kobo or named not in (None, refund.transaction_id):
            self._audit.log(
                "refund.mismatch",
                quote=refund.quote_id,
                amount_kobo=outcome.amount_kobo,
                expected_kobo=refund.amount_kobo,
            )
            return refund
        match outcome.status:
            case "processed" | "failed":
                state = outcome.status
            case "needs-attention":
                state = "needs_attention"
            case _:
                state = "sent"
        return await self._settle(refund, state, outcome.refund_id, outcome.status)

    async def _settle(self, refund: Refund, state: str, refund_id: int | None, status: str) -> Refund:
        """The refund's state, the quote's progress that mirrors it and, once processed, the quote refunded:
        one batch."""
        now = self._clock.now()
        decided = now if state not in UNDECIDED else None
        results = await self._db.batch(
            [
                (_SETTLE, (state, refund_id, status, decided, refund.quote_id)),
                (_MIRROR, (refund.quote_id,)),
                (_REFUNDED, (now, refund.quote_id)),
            ]
        )
        if results[0].changes == 1 and state != refund.state:
            self._told(refund, state, status)
        return await self.get(refund.quote_id) or refund

    def _told(self, refund: Refund, state: str, status: str) -> None:
        if state == "failed":
            self._audit.log(
                "refund.failed", quote=refund.quote_id, amount_kobo=refund.amount_kobo, status=status
            )
        elif state in ("processed", "needs_attention"):
            self._audit.log(f"refund.{state}", quote=refund.quote_id, amount_kobo=refund.amount_kobo)

    async def _mirror(self, quote_id: str) -> None:
        await self._db.execute(_MIRROR, quote_id)

    async def recheck(self, refund: Refund) -> Refund:
        """Asks Paystack about an undecided refund and records the answer. A refund Paystack never had is
        sent again by whoever takes the send."""
        if refund.state not in UNDECIDED:
            return refund
        try:
            found = await self._find(refund)
        except PaystackError:
            return refund
        if found is not None:
            return await self.record(refund, found)
        if await self._take_send(refund):
            return await self.send(await self.get(refund.quote_id) or refund)
        return refund

    async def _take_send(self, refund: Refund) -> bool:
        now = self._clock.now()
        return await self._db.execute(_TAKE_SEND, now, refund.quote_id, now - SEND_STALE_MS) == 1

    async def due_ids(self) -> list[str]:
        """Quotes owing a refund that was never opened, then undecided refunds, oldest first, a while after
        each began."""
        since = self._clock.now() - RECHECK_AFTER_MS
        never = await self._db.rows(
            f"SELECT q.id FROM quotes AS q WHERE {owed_sql('q')} AND q.settled_at < ? "
            "AND NOT EXISTS (SELECT 1 FROM quote_refund AS r WHERE r.quote_id = q.id) "
            "ORDER BY q.settled_at LIMIT ?",
            since,
            RECHECK_LIMIT,
        )
        undecided = await self._db.rows(
            f"SELECT quote_id FROM quote_refund WHERE state IN ({UNDECIDED_SQL}) AND created_at < ? "
            "ORDER BY created_at LIMIT ?",
            since,
            RECHECK_LIMIT,
        )
        return [row["id"] for row in never] + [row["quote_id"] for row in undecided]
