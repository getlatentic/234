# SPDX-License-Identifier: AGPL-3.0-or-later
"""VTpass reversing airtime it had reported delivered (flows/reversal.py): its callback is only a hint, a
requery that answers reversed ends the quote `reversed`, a wallet payment comes back once in the same batch, a
checkout payment is owed a refund, and nothing polls delivered quotes. Simulated VTpass, which reverses an
order from the test routes and sends the callback VTpass sends."""

import asyncio
import base64
import json

import pytest

from checkout.flows.reversal import reverse_if_confirmed
from checkout.http import handle
from checkout.owner import DEFAULT_OWNER
from checkout.transport import Reply
from checkout.vtpass.sim import reversal_update
from checkout.vtpass.sim_store import SimOrder
from tests.airtime_support import paid, quote_input
from tests.support import ScriptedTransport
from tests.wallet_support import entries, fund, journal_of


async def _wallet_paid(stack, **over) -> str:
    issued = await stack.airtime.create_airtime_quote(**quote_input(**over))
    await stack.airtime.approve(issued.quote["id"], issued.approval_token, 50_000, True, funding="wallet")
    return issued.quote["id"]


async def _request_id(stack, quote_id) -> str:
    return (await stack.ledger.get(quote_id)).progress["fulfilment"]["requestId"]


async def _vtpass_reverses(stack, quote_id):
    """VTpass takes the order back and sends its callback; then the queued work runs."""
    answer = await handle(
        stack.app, "POST", f"/test/vtpass-reverse/{await _request_id(stack, quote_id)}", {}, b""
    )
    await stack.run_jobs()
    return answer


def _callback(request_id: str) -> bytes:
    """The reversal callback for any request id, as anyone could send it: it is unsigned."""
    return reversal_update(SimOrder(request_id, "mtn", "08011111111", 500, None, "success", 0), 0)


async def _post_callback(stack, body: bytes):
    answer = await handle(stack.app, "POST", "/hooks/vtpass", {}, body)
    await stack.run_jobs()
    return answer


async def _state(stack, quote_id) -> str:
    return (await stack.ledger.get(quote_id)).state


def _audited(stack, event: str) -> int:
    return [json.loads(line)["event"] for line in stack.audit_lines].count(event)


class TestAWalletPaidOrderReversed:
    async def test_ends_reversed_with_the_money_back_in_the_wallet(self, stack):
        await fund(stack, 200_000)
        quote_id = await _wallet_paid(stack)
        answer = await _vtpass_reverses(stack, quote_id)
        assert json.loads(answer.body) == {"response": "success"}
        assert await _state(stack, quote_id) == "reversed"
        assert [e["kind"] for e in await entries(stack)] == ["fund", "spend", "refund"]
        assert (await entries(stack, "refund"))[0]["amount_kobo"] == 50_000
        assert await journal_of(stack).balance(DEFAULT_OWNER) == 200_000
        assert _audited(stack, "fulfilment.reversed") == _audited(stack, "wallet.refunded") == 1

    async def test_the_card_says_it_was_reversed_and_where_the_money_is(self, stack):
        await fund(stack, 200_000)
        quote_id = await _wallet_paid(stack)
        await _vtpass_reverses(stack, quote_id)
        view = await stack.airtime.status(quote_id)
        assert view["phase"] == "failed" and view["receipt"] is None
        assert (
            "VTpass reversed this order after delivering it. ₦500 is back in the wallet." in view["message"]
        )

    async def test_no_longer_counts_against_the_days_limit(self, stack):
        await fund(stack, 200_000)
        quote_id = await _wallet_paid(stack)
        assert (await stack.ledger.budget()).spent_today_kobo == 50_000
        await _vtpass_reverses(stack, quote_id)
        assert (await stack.ledger.budget()).spent_today_kobo == 0

    async def test_the_same_callback_twice_reverses_and_refunds_once(self, stack):
        await fund(stack, 200_000)
        quote_id = await _wallet_paid(stack)
        await _vtpass_reverses(stack, quote_id)
        await _post_callback(stack, _callback(await _request_id(stack, quote_id)))
        assert len(await entries(stack, "refund")) == 1
        assert _audited(stack, "fulfilment.reversed") == 1

    async def test_requeries_racing_the_callback_refund_once(self, stack):
        await fund(stack, 200_000)
        quote_id = await _wallet_paid(stack)
        await handle(stack.app, "POST", f"/test/vtpass-reverse/{await _request_id(stack, quote_id)}", {}, b"")
        ctx = stack.app.contexts["airtime"]
        racing = [reverse_if_confirmed(ctx, quote_id) for _ in range(6)]
        await asyncio.gather(stack.run_jobs(), *racing)
        assert await _state(stack, quote_id) == "reversed"
        assert len(await entries(stack, "refund")) == 1
        assert await journal_of(stack).balance(DEFAULT_OWNER) == 200_000
        assert _audited(stack, "fulfilment.reversed") == 1


class TestOnlyARequeryMovesAnything:
    async def test_a_callback_vtpass_does_not_confirm_changes_nothing(self, stack):
        await fund(stack, 200_000)
        quote_id = await _wallet_paid(stack)
        await _post_callback(stack, _callback(await _request_id(stack, quote_id)))
        assert await _state(stack, quote_id) == "settled"
        assert await entries(stack, "refund") == []
        assert _audited(stack, "reversal.unconfirmed") == 1

    async def test_a_callback_that_reports_no_reversal_does_not_ask_about_a_delivered_quote(self, stack):
        await fund(stack, 200_000)
        quote_id = await _wallet_paid(stack)
        update = {
            "type": "transaction-update",
            "data": {"code": "000", "requestId": await _request_id(stack, quote_id)},
        }
        await _post_callback(stack, json.dumps(update).encode())
        assert _audited(stack, "recheck.skipped") == 1 and _audited(stack, "reversal.unconfirmed") == 0

    async def test_the_minute_never_asks_about_a_delivered_quote(self, stack):
        await fund(stack, 200_000)
        await _wallet_paid(stack)
        stack.clock.advance(3600)
        await stack.app.background.minute()
        assert stack.jobs.held == []


class TestAReversalOfAnOrderThatIsNotDelivered:
    async def test_before_delivery_is_the_failure_it_always_was(self, stack):
        await fund(stack, 200_000)
        quote_id = await _wallet_paid(stack, phone="201000000000")
        assert await _state(stack, quote_id) == "approved"
        await _vtpass_reverses(stack, quote_id)
        assert await _state(stack, quote_id) == "failed"
        assert len(await entries(stack, "refund")) == 1
        assert _audited(stack, "fulfilment.reversed") == 0

    async def test_of_an_order_already_refunded_changes_nothing(self, stack):
        await fund(stack, 200_000)
        quote_id = await _wallet_paid(stack, phone="100000000000")
        assert await _state(stack, quote_id) == "failed"
        await _post_callback(stack, _callback(await _request_id(stack, quote_id)))
        assert await _state(stack, quote_id) == "failed"
        assert len(await entries(stack, "refund")) == 1
        assert await journal_of(stack).balance(DEFAULT_OWNER) == 200_000


class TestACheckoutPaidOrderReversed:
    async def test_ends_reversed_with_a_refund_owed_and_nothing_from_the_wallet(self, stack):
        await fund(stack, 200_000)
        quote_id = await paid(stack)
        await stack.airtime.verify(quote_id)
        assert await _state(stack, quote_id) == "settled"
        await _vtpass_reverses(stack, quote_id)
        assert await _state(stack, quote_id) == "reversed"
        assert await entries(stack, "refund") == []
        assert _audited(stack, "refund.due") == 1
        view = await stack.airtime.status(quote_id)
        assert view["phase"] == "attention"
        assert view["message"].startswith("VTpass reversed this order after delivering it. Refund due")


class TestTheGuards:
    async def test_only_a_settled_quote_is_reversed(self, stack):
        await fund(stack, 200_000)
        quote_id = await _wallet_paid(stack, phone="100000000000")
        quote, moved = await stack.ledger.reverse(quote_id, {}, [])
        assert (quote.state, moved) == ("failed", False)

    async def test_a_delivered_quote_can_only_be_reversed_and_a_reversed_one_stays(self, stack):
        await fund(stack, 200_000)
        quote_id = await _wallet_paid(stack)
        with pytest.raises(Exception, match="only be reversed"):
            await stack.db.execute("UPDATE quotes SET state = 'refund_due' WHERE id = ?", quote_id)
        await _vtpass_reverses(stack, quote_id)
        with pytest.raises(Exception, match="only be reversed"):
            await stack.db.execute("UPDATE quotes SET state = 'settled' WHERE id = ?", quote_id)

    async def test_the_refund_needs_the_quote_reversed(self, stack):
        await fund(stack, 200_000)
        quote_id = await _wallet_paid(stack)
        sql, params = stack.app.contexts["airtime"].wallet.reversal_refund(DEFAULT_OWNER, quote_id)
        await stack.db.execute(sql, *params)
        assert await entries(stack, "refund") == []

    async def test_the_refund_needs_the_wallet_to_have_paid(self, stack):
        await fund(stack, 200_000)
        quote_id = await paid(stack)
        await stack.airtime.verify(quote_id)
        await journal_of(stack).debit(DEFAULT_OWNER, "spend", 50_000, quote_id, quote_id)
        await _vtpass_reverses(stack, quote_id)
        sql, params = stack.app.contexts["airtime"].wallet.reversal_refund(DEFAULT_OWNER, quote_id)
        await stack.db.execute(sql, *params)
        assert await entries(stack, "refund") == []

    async def test_the_ending_is_told_to_whoever_follows_the_quote(self, stack):
        await fund(stack, 200_000)
        quote_id = await _wallet_paid(stack)
        transport = ScriptedTransport(lambda sent: Reply(200, "{}"))
        object.__setattr__(stack.app.background.delivery, "_transport", transport)
        await stack.db.execute(
            "INSERT INTO event_subscriptions (id, owner, connector, name, quote_id, arguments, url, secret,"
            " expires_at, created_at) VALUES ('sub-1', ?, 'airtime', 'quote.finished', ?, '{}', ?, ?, ?, 0)",
            DEFAULT_OWNER,
            quote_id,
            "https://agent.example/events",
            "whsec_" + base64.b64encode(b"k" * 32).decode(),
            stack.clock.now() + 3_600_000,
        )
        await _vtpass_reverses(stack, quote_id)
        sent = [call.body["data"] for call in transport.calls if call.body.get("name") == "quote.finished"]
        assert [(data["quote_id"], data["state"]) for data in sent] == [(quote_id, "reversed")]
