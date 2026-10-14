# SPDX-License-Identifier: AGPL-3.0-or-later
"""What every connector's flow shares: presenting a quote, the audit around making one, and the gate
every approval passes."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from ..errors import DomainError
from ..ledger import ClaimTerms, Quote
from ..mask import mask_account, mask_phone
from ..money import Kobo, format_naira
from ..present import present_quote
from ..wallet.spending import WalletSpending
from .context import Context, QuoteIssued
from .wallet_leg import wallet_offer


def _masked_target(quote: Quote) -> dict[str, Any]:
    d = quote.details
    match d["kind"]:
        case "transfer":
            return {"account_masked": mask_account(d["accountNumber"]), "bank": d["bankName"]}
        case "airtime" | "data":
            return {"phone_masked": mask_phone(d["phone"]), "network": d["network"]}
        case "food":
            return {"area": d["area"], "items": sum(line["quantity"] for line in d["lines"])}
        case "basket":
            return {"merchant_id": d["merchantId"], "items": sum(line["quantity"] for line in d["lines"])}
        case _:
            return {}


class CardFlow(ABC):
    """A connector's quote lifecycle. Subclasses make quotes and say how an approved one finishes."""

    connector: str

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    async def present(self, quote: Quote) -> dict[str, Any]:
        budget = await self.ctx.ledger.budget()
        view = present_quote(quote, budget, self.ctx.modes, self.ctx.clock, self.ctx.food_step_seconds)
        if offer := await wallet_offer(self.ctx, quote):
            view["wallet"] = offer
        return view

    async def make_quote(self, work: Callable[[], Awaitable[tuple[Quote, bool]]]) -> QuoteIssued:
        """Makes a quote and records that it was made, or that it was refused and why."""
        try:
            quote, replayed = await work()
        except DomainError as error:
            self.ctx.audit.log("quote.rejected", connector=self.connector, code=error.code)
            raise
        self.ctx.audit.log(
            "quote.replayed" if replayed else "quote.created",
            quote=quote.id,
            connector=self.connector,
            kind=quote.kind,
            amount_kobo=quote.amount_kobo,
            **_masked_target(quote),
        )
        return QuoteIssued(await self.present(quote), self.approval_token_of(quote), replayed)

    def approval_token_of(self, quote: Quote) -> str:
        """The token only the card is given: the ledger's, over the quote's id. A flow whose approval is bound
        to more than the id says so here and in `token_is_valid`."""
        return self.ctx.ledger.approval_token(quote.id)

    async def token_is_valid(self, quote_id: str, token: str) -> bool:
        return self.ctx.ledger.check_approval_token(quote_id, token)

    async def authorise_approval(
        self,
        quote_id: str,
        token: str,
        displayed_amount_kobo: Kobo,
        wallet: WalletSpending | None = None,
        terms: ClaimTerms | None = None,
    ) -> tuple[Quote, bool]:
        """The token proves the call came from the card the person was looking at, and the displayed
        amount proves the card and the server agree on it. With `wallet`, the wallet pays for the approval;
        with `terms`, the funding source they name does."""
        ledger, audit = self.ctx.ledger, self.ctx.audit
        if not await self.token_is_valid(quote_id, token):
            audit.log("approval.denied", quote=quote_id, why="token")
            raise DomainError(
                "APPROVAL_DENIED",
                "Only the approval card can approve a payment. Show the person the card and let "
                "them press Approve.",
            )
        quote = await ledger.require(quote_id, self.connector)
        if displayed_amount_kobo != quote.amount_kobo:
            audit.log("approval.denied", quote=quote.id, why="amount", displayed_kobo=displayed_amount_kobo)
            raise DomainError(
                "AMOUNT_MISMATCH",
                f"The card showed {format_naira(displayed_amount_kobo)} but this quote is for "
                f"{format_naira(quote.amount_kobo)}. Nothing was approved.",
            )
        if wallet is None:
            quote, claimed = await ledger.claim_approval(quote.id, self.connector, terms)
        else:
            quote, claimed = await wallet.pay(ledger, quote)
        if claimed:
            paid_by = {"funding": "wallet"} if wallet else {}
            if terms is not None:
                paid_by = {"funding": terms.progress["funding"]}
            audit.log(
                "approval.claimed", quote=quote.id, kind=quote.kind, amount_kobo=quote.amount_kobo, **paid_by
            )
        return quote, claimed

    @abstractmethod
    async def approve(
        self, quote_id: str, token: str, displayed_amount_kobo: Kobo, readback_confirmed: bool | None = None
    ) -> dict[str, Any]: ...

    async def approve_from_wallet(
        self, quote_id: str, token: str, displayed_amount_kobo: Kobo, readback_confirmed: bool | None = None
    ) -> dict[str, Any]:
        """The approval, paid from the person's wallet instead of a checkout, where the flow offers it."""
        raise DomainError(
            "WALLET_UNAVAILABLE", "Paying from the wallet is not offered here. Nothing was taken."
        )

    async def approve_external(
        self, quote_id: str, token: str, displayed_amount_kobo: Kobo, readback_confirmed: bool | None = None
    ) -> dict[str, Any]:
        """The approval of a quote the person's own account at the provider pays, where the flow has such."""
        raise DomainError(
            "FUNDING_UNAVAILABLE",
            "Paying from an account at the provider is not offered here. Nothing was taken.",
        )

    @abstractmethod
    async def verify(self, quote_id: str, checkout_closed: bool = False) -> dict[str, Any]: ...

    async def decline(self, quote_id: str, token: str) -> dict[str, Any]:
        ledger = self.ctx.ledger
        if not await self.token_is_valid(quote_id, token):
            self.ctx.audit.log("approval.denied", quote=quote_id, why="token")
            raise DomainError("APPROVAL_DENIED", "Only the approval card can decline a quote.")
        quote = await ledger.require(quote_id, self.connector)
        declined = await ledger.transition(quote.id, ("open",), "declined")
        self.ctx.audit.log("declined", quote=quote.id)
        return await self.present(declined)

    async def card_meta(self, quote_id: str) -> dict[str, Any] | None:
        """What only the card is given about a quote, in the result's `_meta`: while the person is at the
        checkout, the access code that opens Paystack's checkout as a popup in the page. It is never in the
        text, in the structured content or in anything a model or a log holds."""
        if not self.ctx.inline_checkout:
            return None
        quote = await self.ctx.ledger.require(quote_id, self.connector)
        code = quote.progress.get("accessCode")
        waiting = quote.state == "approved" and quote.progress.get("paymentStatus") != "success"
        return {"paystack": {"accessCode": code}} if code and waiting else None

    async def status(self, quote_id: str) -> dict[str, Any]:
        return await self.verify(quote_id)
