# SPDX-License-Identifier: AGPL-3.0-or-later
"""An airtime or data order VTpass took back after reporting it delivered (docs/wallet.md, "Reversals").

VTpass's callback says so unsigned, so only a requery that answers reversed moves anything: the quote goes
from settled to reversed and, when the wallet paid, a `refund` of what its hold took rides in the same batch,
so the two land together or not at all. The ledger's trigger lets a settled quote become nothing else, the
refund's own WHERE requires the quote reversed and paid from the wallet, and UNIQUE (owner, kind, ref) makes
it once: a callback delivered twice, or racing a requery, reverses and refunds once.

A quote paid at the checkout is reversed too and owes its payer a Paystack refund, as a `refund_due` quote
does: it is audited as `refund.due` and the refund is asked for (refunds/). The quote stays reversed.
"""

from typing import Any

from ..ledger import Quote
from ..metrics import WRITTEN
from ..money import format_naira
from ..vtpass.api import VtpassOutcome
from ..wallet.spending import paid_from_wallet
from .checkout_leg import ask_refund
from .context import Context

CONNECTOR = "airtime"
REVERSED = "VTpass reversed this order after delivering it."


def _patch(quote: Quote, outcome: VtpassOutcome, to_wallet: bool) -> dict[str, Any]:
    fulfilment = {**quote.progress["fulfilment"], "status": "reversed", "description": outcome.description}
    back = f" {format_naira(quote.amount_kobo)} is back in the wallet." if to_wallet else ""
    return {"fulfilment": fulfilment, "failureReason": f"{REVERSED}{back}"}


async def _reverse(ctx: Context, quote: Quote, outcome: VtpassOutcome) -> Quote:
    ledger, audit = ctx.ledger, ctx.audit
    wallet = ctx.wallet if paid_from_wallet(quote) else None
    to_wallet = wallet is not None
    refund = [wallet.reversal_refund(ledger.owner(), quote.id)] if wallet else []
    reversed_quote, moved = await ledger.reverse(quote.id, _patch(quote, outcome, to_wallet), refund)
    if not moved:
        return reversed_quote
    audit.log("fulfilment.reversed", quote=quote.id, code=outcome.code)
    if wallet is not None:
        audit.log("wallet.refunded", quote=quote.id, amount_kobo=quote.amount_kobo)
        wallet.journal.metrics.wallet("refund", WRITTEN, quote.amount_kobo)
        return reversed_quote
    audit.log("refund.due", quote=quote.id, why="reversed after delivery")
    return await ask_refund(ctx, reversed_quote)


async def reverse_if_confirmed(ctx: Context, quote_id: str) -> Quote:
    """Asks VTpass about a delivered quote once more, and reverses it only when VTpass answers reversed."""
    quote = await ctx.ledger.require(quote_id, CONNECTOR)
    request_id = (quote.progress.get("fulfilment") or {}).get("requestId")
    if quote.state != "settled" or request_id is None or ctx.vtpass is None:
        return quote
    outcome = await ctx.vtpass.requery(request_id)
    if not outcome.reversed:
        ctx.audit.log("reversal.unconfirmed", quote=quote.id, code=outcome.code)
        return quote
    return await _reverse(ctx, quote, outcome)
