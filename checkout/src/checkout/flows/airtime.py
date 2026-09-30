# SPDX-License-Identifier: AGPL-3.0-or-later
"""Airtime and data through VTpass. The person pays through Paystack first; delivery follows the
confirmed payment.

Every step that talks to VTpass is guarded the way money is: the request id is fixed once per quote by
one conditional write, one caller at a time holds the provider step, and the outcome is recorded by a
statement that only applies while the quote is still approved. A caller that finds the step taken
reports the quote as it stands; the card's next poll picks up the result.
"""

from typing import Any

from ..amount_floor import assert_above_floor
from ..errors import DomainError
from ..ledger import NewQuote, Quote, request_hash
from ..mask import group_phone
from ..money import Kobo
from ..network import NETWORK_LABEL, Network, network_of_number
from ..vtpass.api import AirtimeOrder, DataOrder, DataPlan, VtpassApi, VtpassError, VtpassOutcome
from ..vtpass.phone import normalise_phone
from ..vtpass.recipient import number_for_vtpass
from ..vtpass.request_id import vtpass_request_id
from .base import CardFlow
from .checkout_leg import STEP_STALE_MS, begin_checkout, check_payment
from .context import Context, QuoteIssued
from .inputs import assert_idempotency_key, confirm_stated_amount
from .provider_error import as_domain_error

KOBO_PER_NAIRA = 100


def _assert_airtime_amount(amount_kobo: Kobo) -> None:
    assert_above_floor(amount_kobo)
    if amount_kobo % KOBO_PER_NAIRA != 0:
        raise DomainError("INVALID_INPUT", "Airtime must be a whole number of naira.")


class AirtimeFlow(CardFlow):
    connector = "airtime"

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        if ctx.vtpass is None:
            raise ValueError("The airtime connector needs a VTpass client.")
        self.vtpass: VtpassApi = ctx.vtpass

    async def _assert_vtpass_ready(self, amount_kobo: Kobo) -> None:
        """Nobody is asked to pay for what VTpass will not deliver: before a quote, the account must be
        accepted and its wallet must cover the order."""
        access = await self.vtpass.check_access()
        if not access.ok:
            raise DomainError(
                "PROVIDER_ERROR",
                f"{access.reason} Airtime and data cannot be delivered, so nothing was quoted. The owner "
                'should check the VTpass sandbox profile (API authentication type must be "all" or API '
                "keys) and the VTPASS_* secrets, then redeploy.",
            )
        if access.balance_kobo is not None and access.balance_kobo < amount_kobo:
            raise DomainError(
                "PROVIDER_ERROR",
                "The VTpass sandbox wallet holds less than this order costs, so nothing was quoted.",
            )

    def _assert_number_on_network(self, network: Network, number: str) -> None:
        """The simulated VTpass delivers to any valid number, so a number quoted on the wrong network is
        caught here, before anyone pays. The real sandbox is left to say what it says, and a number that
        moved networks keeps its old prefix, which is why nothing real is refused on prefix alone."""
        if self.ctx.modes.vtpass != "simulated":
            return
        owner = network_of_number(number)
        if owner is not None and owner != network:
            raise DomainError(
                "INVALID_INPUT",
                f"{group_phone(number)} is a {NETWORK_LABEL[owner]} number, not {NETWORK_LABEL[network]}. "
                f"Quote it as {NETWORK_LABEL[owner]}, or check the number.",
            )

    async def _quote(self, new: NewQuote) -> tuple[Quote, bool]:
        ledger = self.ctx.ledger
        replayed = await ledger.replay(new.connector, new.idempotency_key, new.request_hash)
        if replayed:
            return replayed, True
        await ledger.assert_quotable(new.amount_kobo)
        await self._assert_vtpass_ready(new.amount_kobo)
        return await ledger.create(new)

    async def create_airtime_quote(
        self,
        *,
        network: Network,
        phone: str,
        amount_kobo: Kobo,
        amount_as_user_said: str,
        idempotency_key: str,
    ) -> QuoteIssued:
        async def work():
            assert_idempotency_key(idempotency_key)
            number = normalise_phone(phone)
            self._assert_number_on_network(network, number)
            confirm_stated_amount(amount_kobo, amount_as_user_said)
            _assert_airtime_amount(amount_kobo)
            label = NETWORK_LABEL[network]
            return await self._quote(
                NewQuote(
                    connector=self.connector,
                    kind="airtime",
                    amount_kobo=amount_kobo,
                    description=f"{label} airtime",
                    merchant=label,
                    merchant_ref=None,
                    details={"kind": "airtime", "network": network, "phone": number},
                    idempotency_key=idempotency_key,
                    request_hash=request_hash(
                        kind="airtime", network=network, phone=number, amount_kobo=amount_kobo
                    ),
                )
            )

        return await self.make_quote(work)

    async def list_data_plans(self, network: Network) -> list[DataPlan]:
        try:
            return await self.vtpass.data_plans(network)
        except VtpassError as error:
            raise as_domain_error(error, "list the data plans") from error

    async def create_data_quote(
        self, *, network: Network, phone: str, plan_code: str, idempotency_key: str
    ) -> QuoteIssued:
        async def work():
            assert_idempotency_key(idempotency_key)
            number = normalise_phone(phone)
            self._assert_number_on_network(network, number)
            label = NETWORK_LABEL[network]
            plan = next((p for p in await self.list_data_plans(network) if p.code == plan_code), None)
            if plan is None:
                raise DomainError(
                    "INVALID_INPUT",
                    f"There is no plan {plan_code} for {label}. Call list_data_plans and use one of its "
                    f"codes.",
                )
            return await self._quote(
                NewQuote(
                    connector=self.connector,
                    kind="data",
                    amount_kobo=plan.amount_kobo,
                    description=f"{plan.name} ({label} data)",
                    merchant=label,
                    merchant_ref=None,
                    details={
                        "kind": "data",
                        "network": network,
                        "phone": number,
                        "planCode": plan.code,
                        "planName": plan.name,
                    },
                    idempotency_key=idempotency_key,
                    request_hash=request_hash(
                        kind="data", network=network, phone=number, plan_code=plan.code
                    ),
                )
            )

        return await self.make_quote(work)

    async def approve(
        self, quote_id: str, token: str, displayed_amount_kobo: Kobo, readback_confirmed: bool | None = None
    ) -> dict[str, Any]:
        if readback_confirmed is not True:
            self.ctx.audit.log("approval.denied", quote=quote_id, why="read-back")
            raise DomainError(
                "READBACK_REQUIRED",
                "The person must confirm the number and amount they were read back before this can be "
                "approved.",
            )
        quote, _ = await self.authorise_approval(quote_id, token, displayed_amount_kobo)
        return await self.present(await begin_checkout(self.ctx, quote))

    async def verify(self, quote_id: str, checkout_closed: bool = False) -> dict[str, Any]:
        quote = await self.ctx.ledger.require(quote_id, self.connector)
        checked = await check_payment(self.ctx, quote, checkout_closed)
        if not checked.paid or checked.quote.state != "approved":
            return await self.present(checked.quote)
        return await self.present(await self._deliver(checked.quote))

    async def _fulfilment(self, quote: Quote) -> dict[str, Any]:
        """The order's request id and how many times VTpass has been asked, fixed once per quote."""
        ledger = self.ctx.ledger
        if quote.progress.get("fulfilment"):
            return quote.progress["fulfilment"]
        proposed = {
            "requestId": vtpass_request_id(self.ctx.clock, quote.id),
            "status": "pending",
            "attempts": 0,
        }
        if await ledger.set_progress_once(quote.id, "fulfilment", proposed):
            self.ctx.audit.log("fulfilment.started", quote=quote.id, request=proposed["requestId"])
        current = await ledger.get(quote.id)
        return current.progress["fulfilment"] if current else proposed

    async def _deliver(self, quote: Quote) -> Quote:
        ledger = self.ctx.ledger
        fulfilment = await self._fulfilment(quote)
        if not await ledger.acquire_step(quote.id, STEP_STALE_MS):
            return await ledger.require(quote.id, self.connector)
        try:
            outcome = await self._ask_vtpass(quote, fulfilment)
        except Exception:
            await ledger.patch_progress(quote.id, {"inFlightSince": None})
            raise
        return await self._record(quote.id, fulfilment, outcome)

    async def _ask_vtpass(self, quote: Quote, fulfilment: dict[str, Any]) -> VtpassOutcome:
        if fulfilment["attempts"] == 0:
            return await self._order(quote, fulfilment["requestId"])
        outcome = await self.vtpass.requery(fulfilment["requestId"])
        return await self._order(quote, fulfilment["requestId"]) if outcome.unknown_request else outcome

    def _recipient(self, quote: Quote) -> str:
        """The number VTpass receives. When it is not the one the person typed, the audit log says so."""
        typed = quote.details["phone"]
        sent = number_for_vtpass(self.ctx.modes.vtpass or "simulated", typed)
        if sent != typed:
            self.ctx.audit.log(
                "vtpass.number_substituted", quote=quote.id, typed=typed, sent="sandbox success number"
            )
        return sent

    async def _order(self, quote: Quote, request_id: str) -> VtpassOutcome:
        d = quote.details
        if d["kind"] == "airtime":
            return await self.vtpass.buy_airtime(
                AirtimeOrder(request_id, d["network"], self._recipient(quote), quote.amount_kobo)
            )
        if d["kind"] == "data":
            order = DataOrder(
                request_id, d["network"], self._recipient(quote), d["planCode"], quote.amount_kobo
            )
            return await self.vtpass.buy_data(order)
        raise ValueError("Not an airtime or data quote.")

    async def _record(self, quote_id: str, before: dict[str, Any], outcome: VtpassOutcome) -> Quote:
        """Writes what VTpass said and lets go of the provider step in one statement that applies only
        while the quote is still approved."""
        ledger, audit = self.ctx.ledger, self.ctx.audit
        seen = {
            "requestId": before["requestId"],
            "status": outcome.status,
            "description": outcome.description,
            "attempts": before["attempts"] + 1,
        }
        patch: dict[str, Any] = {"fulfilment": seen, "inFlightSince": None}
        try:
            match outcome.status:
                case "delivered":
                    audit.log("fulfilment.delivered", quote=quote_id, request=before["requestId"])
                    return await ledger.transition(quote_id, ("approved",), "settled", patch)
                case "failed":
                    audit.log("fulfilment.failed", quote=quote_id, code=outcome.code)
                    audit.log("refund.due", quote=quote_id, why="paid, not delivered")
                    reason = f"VTpass did not deliver: {outcome.description}."
                    return await ledger.transition(
                        quote_id, ("approved",), "refund_due", {**patch, "failureReason": reason}
                    )
                case _:
                    if before["attempts"] == 0:
                        audit.log("fulfilment.pending", quote=quote_id, code=outcome.code)
                    return await ledger.patch_progress(quote_id, patch, only_state="approved")
        except DomainError:
            return await ledger.require(quote_id, self.connector)
