# SPDX-License-Identifier: AGPL-3.0-or-later
"""The airtime flow under races, crashes and a VTpass that will not deliver: what D1 without
transactions makes possible, and the guards that hold."""

import asyncio
import json

import pytest

from checkout.config import SimulatorSettings
from checkout.errors import DomainError
from checkout.vtpass.api import VtpassOutcome
from checkout.vtpass.interpret import no_confirmation
from tests.airtime_support import approve, code_of, paid, quote_input, vtpass_orders
from tests.support import CountingVtpass, make_stack


class TestRacesAndCrashes:
    async def test_vtpass_is_asked_once_however_many_verify_together(self, stack):
        quote_id = await paid(stack)
        counting = CountingVtpass(stack.app.contexts["airtime"].vtpass)
        stack.override("airtime", vtpass=counting)
        views = await asyncio.gather(*[stack.flow("airtime").verify(quote_id) for _ in range(20)])
        assert counting.calls == {"buy_airtime": 1}
        assert await vtpass_orders(stack) == 1
        assert {v["phase"] for v in views} <= {"processing", "succeeded"}
        assert "succeeded" in {v["phase"] for v in views}
        assert (await stack.flow("airtime").verify(quote_id))["phase"] == "succeeded"
        assert counting.calls == {"buy_airtime": 1}

    async def test_the_request_id_is_chosen_once_however_many_verify_together(self, stack):
        quote_id = await paid(stack, phone="201000000000")
        stack.clock.advance(0)

        async def verify_later(seconds):
            stack.clock.advance(seconds)
            return await stack.airtime.verify(quote_id)

        await asyncio.gather(*[verify_later(61) for _ in range(6)])
        started = [json.loads(line) for line in stack.audit_lines if '"fulfilment.started"' in line]
        assert len(started) == 1

    async def test_a_reply_lost_after_the_order_was_placed_is_resolved_by_the_same_request_id(self, stack):
        """The crash window: VTpass took the order, the reply was never recorded, the step lock went stale."""
        quote_id = await paid(stack)
        ctx = stack.app.contexts["airtime"]
        real = ctx.vtpass

        class LosesTheReplyOnce:
            def __init__(self):
                self.lost = False

            async def buy_airtime(self, order):
                outcome = await real.buy_airtime(order)
                if not self.lost:
                    self.lost = True
                    raise asyncio.CancelledError  # an evicted Worker runs no handler
                return outcome

            def __getattr__(self, name):
                return getattr(real, name)

        stack.override("airtime", vtpass=LosesTheReplyOnce())
        with pytest.raises(asyncio.CancelledError):
            await stack.flow("airtime").verify(quote_id)
        assert await vtpass_orders(stack) == 1
        assert (await stack.airtime.verify(quote_id))["phase"] == "processing", "the step lock is still held"
        stack.clock.advance(31)
        again = await stack.airtime.verify(quote_id)
        assert again["phase"] == "processing", (
            "the second order is answered 'already exists', which is pending"
        )
        assert (await stack.airtime.verify(quote_id))["phase"] == "succeeded", (
            "then a requery finds it delivered"
        )
        assert await vtpass_orders(stack) == 1

    async def test_lets_go_of_the_step_when_something_unexpected_goes_wrong(self, stack):
        quote_id = await paid(stack)
        real = stack.app.contexts["airtime"].vtpass

        class Breaks:
            broke = False

            async def buy_airtime(self, order):
                outcome = await real.buy_airtime(order)
                if not Breaks.broke:
                    Breaks.broke = True
                    raise RuntimeError("unexpected")
                return outcome

            def __getattr__(self, name):
                return getattr(real, name)

        stack.override("airtime", vtpass=Breaks())
        with pytest.raises(RuntimeError):
            await stack.flow("airtime").verify(quote_id)
        assert (await stack.airtime.verify(quote_id))["phase"] == "processing", (
            "sent again, answered 'already exists'"
        )
        assert (await stack.airtime.verify(quote_id))["phase"] == "succeeded"
        assert await vtpass_orders(stack) == 1

    async def test_an_outcome_arriving_after_the_quote_moved_on_is_not_recorded(self, stack):
        quote_id = await paid(stack)
        flow, ledger = stack.airtime, stack.ledger
        quote = await ledger.get(quote_id)
        fulfilment = await flow._fulfilment(quote)
        await ledger.transition(
            quote_id, ("approved",), "settled", {"fulfilment": {**fulfilment, "status": "delivered"}}
        )
        late = await flow._record(quote_id, fulfilment, VtpassOutcome("failed", "016", "TOO LATE"))
        assert late.state == "settled"
        assert (await ledger.get(quote_id)).state == "settled"

    async def test_a_pending_outcome_arriving_after_the_quote_moved_on_leaves_the_record_alone(self, stack):
        quote_id = await paid(stack)
        flow, ledger = stack.airtime, stack.ledger
        fulfilment = await flow._fulfilment(await ledger.get(quote_id))
        delivered = {**fulfilment, "status": "delivered", "attempts": 1}
        await ledger.transition(quote_id, ("approved",), "settled", {"fulfilment": delivered})
        await flow._record(quote_id, fulfilment, VtpassOutcome("pending", "000", "TRANSACTION PENDING"))
        assert (await ledger.get(quote_id)).progress["fulfilment"]["status"] == "delivered"

    async def test_an_order_vtpass_never_received_is_sent_again_when_its_request_id_is_unknown(self, stack):
        quote_id = await paid(stack)
        real = stack.app.contexts["airtime"].vtpass

        class LosesTheFirstOrder:
            lost = False

            async def buy_airtime(self, order):
                if not LosesTheFirstOrder.lost:
                    LosesTheFirstOrder.lost = True
                    return no_confirmation("no reply")
                return await real.buy_airtime(order)

            def __getattr__(self, name):
                return getattr(real, name)

        stack.override("airtime", vtpass=LosesTheFirstOrder())
        assert (await stack.flow("airtime").verify(quote_id))["phase"] == "processing"
        assert await vtpass_orders(stack) == 0, "the order never reached VTpass"
        assert (await stack.airtime.verify(quote_id))["phase"] == "succeeded", (
            "the requery said unknown, so it was sent"
        )
        assert await vtpass_orders(stack) == 1

    async def test_the_daily_limit_is_shared_with_the_other_connectors(self):
        stack = make_stack(per_payment_limit_kobo=5_000_000, daily_limit_kobo=6_000_000)
        pay = await stack.payments.create_quote(
            amount_kobo=4_000_000, amount_as_user_said="40k", description="x", merchant="y",
            merchant_ref=None, idempotency_key="pay-share-0001",
        )  # fmt: skip
        big = await stack.airtime.create_airtime_quote(
            **quote_input(amount_kobo=1_900_000, amount_as_user_said="19k")
        )
        small = await stack.airtime.create_airtime_quote(
            **quote_input(amount_kobo=200_000, amount_as_user_said="2k")
        )
        await stack.payments.approve(pay.quote["id"], pay.approval_token, 4_000_000)
        await approve(stack.airtime, big, 1_900_000)
        assert await code_of(approve(stack.airtime, small, 200_000)) == "LIMIT_DAILY"

    async def test_a_quote_that_would_not_fit_the_daily_limit_is_refused_at_once(self):
        stack = make_stack(per_payment_limit_kobo=5_000_000, daily_limit_kobo=6_000_000)
        pay = await stack.payments.create_quote(
            amount_kobo=4_000_000, amount_as_user_said="40k", description="x", merchant="y",
            merchant_ref=None, idempotency_key="pay-share-0002",
        )  # fmt: skip
        await stack.payments.approve(pay.quote["id"], pay.approval_token, 4_000_000)
        refused = stack.airtime.create_airtime_quote(
            **quote_input(amount_kobo=2_500_000, amount_as_user_said="25k")
        )
        assert await code_of(refused) == "LIMIT_DAILY"


class TestWhenVtpassWouldNotDeliver:
    async def test_does_not_quote_so_nobody_pays_when_the_accounts_credentials_are_refused(self):
        stack = make_stack(simulator=SimulatorSettings(vtpass_rejects_credentials=True))
        flow = stack.airtime
        refused = flow.create_airtime_quote(**quote_input())
        assert await code_of(refused) == "PROVIDER_ERROR"
        with pytest.raises(
            DomainError, match=r"refused this account's credentials \(HTTP 401\).*nothing was quoted.*API"
        ):
            await flow.create_airtime_quote(**quote_input())
        with pytest.raises(DomainError, match="nothing was quoted"):
            await flow.create_data_quote(
                network="mtn", phone="08011111111", plan_code="mtn-10mb-100", idempotency_key="data-key-9001"
            )
        assert (await stack.ledger.budget()).spent_today_kobo == 0
        assert await stack.count("quotes") == 0

    async def test_does_not_quote_an_order_the_vtpass_wallet_cannot_cover(self):
        stack = make_stack()
        real_client = stack.app.contexts["airtime"].vtpass

        class LowWallet:
            async def check_access(self):
                from checkout.vtpass.api import AccessCheck

                return AccessCheck(True, balance_kobo=10_000)

            def __getattr__(self, name):
                return getattr(real_client, name)

        stack.override("airtime", vtpass=LowWallet())
        flow = stack.flow("airtime")
        assert await code_of(flow.create_airtime_quote(**quote_input())) == "PROVIDER_ERROR"
        assert await flow.create_airtime_quote(**quote_input(amount_kobo=10_000, amount_as_user_said="100"))

    async def test_a_quote_over_the_limits_is_refused_before_vtpass_is_asked(self):
        stack = make_stack(per_payment_limit_kobo=100_000, daily_limit_kobo=200_000)
        asked = []
        real_client = stack.app.contexts["airtime"].vtpass

        class Spy:
            async def check_access(self):
                asked.append(1)
                return await real_client.check_access()

        stack.override("airtime", vtpass=Spy())
        refused = stack.flow("airtime").create_airtime_quote(
            **quote_input(amount_kobo=500_000, amount_as_user_said="5k")
        )
        assert await code_of(refused) == "LIMIT_PER_PAYMENT"
        assert asked == []
