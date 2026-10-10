# SPDX-License-Identifier: AGPL-3.0-or-later
"""The payment leg of a quote paid from the wallet: who may pay that way, the offer on the approval card, and
the refund when the provider fails after approval. The approval itself is the wallet's hold, claim and release
(wallet/spending.py)."""

from typing import Any

from ..errors import DomainError
from ..ledger import Quote
from ..money import format_naira
from ..wallet.access import account_of_call
from ..wallet.spending import WalletSpending, paid_from_wallet
from .context import Context


def wallet_of(ctx: Context) -> WalletSpending:
    if ctx.wallet is None:
        raise DomainError(
            "WALLET_UNAVAILABLE", "Paying from the wallet is not offered here. Nothing was taken."
        )
    return ctx.wallet


async def wallet_offer(ctx: Context, quote: Quote) -> dict[str, Any] | None:
    """What the approval card offers besides the checkout: paying from the wallet, for an account whose
    balance covers an open quote. None otherwise, and the card is as it was."""
    if ctx.wallet is None or quote.state != "open":
        return None
    owner = account_of_call()
    if owner is None:
        return None
    balance = await ctx.wallet.journal.balance(owner)
    if balance < quote.amount_kobo:
        return None
    return {"balanceKobo": balance, "balance": format_naira(balance)}


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
