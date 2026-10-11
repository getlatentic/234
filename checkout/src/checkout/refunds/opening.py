# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opening a quote's refund: the payment is asked about first, and only a payment Paystack verified as a
success of exactly the quote's amount, in naira, is refunded, so a quote never paid is never refunded.

The refund's row is then the claim to send it: one INSERT, keyed by the quote, whose WHERE holds the quote
still owing a refund (refunds/owed.py) for exactly that amount under that reference. Of any number of callers
only the one whose INSERT landed sends. A payment Paystack does not hold as such is recorded `refused`, once,
and nothing is sent: an operator follows it up (`SELECT * FROM quote_refund WHERE state = 'refused'`)."""

from dataclasses import dataclass

from ..audit import Audit
from ..clock import Clock
from ..db import Db
from ..ledger import Quote, quote_of
from ..money import format_naira
from ..paystack.api import PaystackApi, PaystackError, TransactionCheck
from .owed import owed_sql, owes_refund

_OPEN = (
    "INSERT INTO quote_refund (quote_id, owner, amount_kobo, transaction_reference, transaction_id, state, "
    "why, sending_since, created_at, decided_at) "
    "SELECT q.id, q.owner, q.amount_kobo, ?, ?, ?, ?, ?, ?, ? FROM quotes AS q "
    "WHERE q.id = ? AND q.amount_kobo = ? AND json_extract(q.progress, '$.paystackReference') = ? "
    f"AND {owed_sql('q')} "
    "ON CONFLICT (quote_id) DO NOTHING"
)


@dataclass(frozen=True)
class Opened:
    """Whether this caller opened the refund, and, when it did, whether it now sends it."""

    opened: bool
    sends: bool


NOT_OPENED = Opened(False, False)


def unpaid_reason(quote: Quote, check: TransactionCheck) -> str | None:
    """Why Paystack's answer about the payment is not one to refund the quote's whole amount for."""
    if check.status != "success":
        return f"Paystack reports the payment {check.status}."
    if check.amount_kobo != quote.amount_kobo or check.currency != "NGN":
        return (
            f"Paystack holds {format_naira(check.amount_kobo)} {check.currency} "
            f"for a {format_naira(quote.amount_kobo)} quote."
        )
    if check.transaction_id is None:
        return "Paystack named no transaction to refund."
    return None


class RefundOpening:
    def __init__(self, db: Db, clock: Clock, audit: Audit) -> None:
        self._db, self._clock, self._audit = db, clock, audit

    async def owing(self, quote_id: str) -> Quote | None:
        """The one read here that names no owner: a refund is followed outside any request of its owner."""
        row = await self._db.row("SELECT * FROM quotes WHERE id = ?", quote_id)
        quote = quote_of(row) if row else None
        return quote if quote is not None and owes_refund(quote) else None

    async def open(self, quote: Quote, paystack: PaystackApi) -> Opened:
        reference = quote.progress["paystackReference"]
        try:
            check = await paystack.verify_transaction(reference)
        except PaystackError as error:
            if error.retryable:
                self._audit.log("refund.unchecked", quote=quote.id)
                return NOT_OPENED
            return await self._refuse(quote, reference, None, str(error))
        why = unpaid_reason(quote, check)
        if why is not None:
            return await self._refuse(quote, reference, check.transaction_id, why)
        opened = await self._insert(quote, reference, check.transaction_id, "sent", None)
        if opened:
            self._audit.log("refund.opened", quote=quote.id, amount_kobo=quote.amount_kobo)
        return Opened(opened, opened)

    async def _refuse(self, quote: Quote, reference: str, transaction_id: int | None, why: str) -> Opened:
        refused = await self._insert(quote, reference, transaction_id, "refused", why)
        if refused:
            self._audit.log("refund.refused", quote=quote.id, why=why)
        return Opened(refused, False)

    async def _insert(
        self, quote: Quote, reference: str, transaction_id: int | None, state: str, why: str | None
    ) -> bool:
        """A refund opened to be sent is taken for sending by this caller; a refused one is decided."""
        now = self._clock.now()
        sending, decided = (now, None) if state == "sent" else (None, now)
        changed = await self._db.execute(
            _OPEN, reference, transaction_id, state, why, sending, now, decided, quote.id, quote.amount_kobo,
            reference,
        )  # fmt: skip
        return changed == 1
