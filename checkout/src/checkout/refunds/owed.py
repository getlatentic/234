# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which quotes owe their payer a Paystack refund, and asking for it.

A quote owes one when its order failed after it was paid (`refund_due`) or its provider reversed it after
delivery (`reversed`), it was paid at the checkout (it has a Paystack reference) and not from the wallet,
which refunds to the wallet itself (wallet/spending.py). A transfer is never paid at the checkout, so it
never owes one. The same rule is SQL in every statement that opens a refund (refunds/opening.py)."""

from ..audit import Audit
from ..jobs import Jobs
from ..ledger import Quote
from ..wallet.spending import paid_from_wallet

OWING_STATES = ("refund_due", "reversed")


def owed_sql(quote: str) -> str:
    """The rule, on the `quotes` row named `quote`."""
    return (
        f"{quote}.state IN ('refund_due', 'reversed') "
        f"AND json_extract({quote}.progress, '$.funding') IS NOT 'wallet' "
        f"AND json_extract({quote}.progress, '$.paystackReference') IS NOT NULL"
    )


def owes_refund(quote: Quote) -> bool:
    return (
        quote.state in OWING_STATES
        and not paid_from_wallet(quote)
        and quote.progress.get("paystackReference") is not None
    )


class RefundRequests:
    """Asks for a quote's refund as a job, the moment a flow ends a quote owing one. The jobs are set once the
    background work is built (background.py); until then, and in a test without them, the minute asks."""

    def __init__(self, audit: Audit) -> None:
        self._audit = audit
        self.jobs: Jobs | None = None

    async def ask(self, quote: Quote) -> Quote:
        if owes_refund(quote) and self.jobs is not None:
            await self.jobs.send({"kind": "refund", "quote": quote.id, "source": "ended"})
            self._audit.log("refund.asked", quote=quote.id)
        return quote
