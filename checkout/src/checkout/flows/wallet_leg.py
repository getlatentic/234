# SPDX-License-Identifier: AGPL-3.0-or-later
"""The payment leg of a quote paid from the wallet: who may pay that way, and the refund when the provider
fails after approval. The approval itself is the wallet's hold, claim and release (wallet/spending.py)."""

from ..errors import DomainError
from ..ledger import Quote
from ..money import format_naira
from ..wallet.spending import WalletSpending, paid_from_wallet
from .context import Context


def wallet_of(ctx: Context) -> WalletSpending:
    if ctx.wallet is None:
        raise DomainError(
            "WALLET_UNAVAILABLE", "Paying from the wallet is not offered here. Nothing was taken."
        )
    return ctx.wallet


async def refund_to_wallet(ctx: Context, quote: Quote) -> Quote:
    """A wallet-paid quote its provider failed gets its money back in the wallet and ends as failed, so it
    no longer counts against the day's limits. Run on every check, so a refund interrupted halfway is
    finished by the next one; the refund is keyed by the quote and lands once."""
    if ctx.wallet is None or quote.state != "refund_due" or not paid_from_wallet(quote):
        return quote
    ledger = ctx.ledger
    if not await ctx.wallet.refund(ledger.owner(), quote.id):
        return quote
    ctx.audit.log("wallet.refunded", quote=quote.id, amount_kobo=quote.amount_kobo)
    reason = quote.progress.get("failureReason") or "The order could not be completed."
    back = f"{reason} {format_naira(quote.amount_kobo)} is back in the wallet."
    return await ledger.transition(quote.id, ("refund_due",), "failed", {"failureReason": back})
