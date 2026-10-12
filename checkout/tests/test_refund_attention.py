# SPDX-License-Identifier: AGPL-3.0-or-later
"""The refunds only an operator can finish (refunds/attention.py): failed, refused, held by Paystack for the
payer's bank account, or owed and never opened; listed at GET /ops/refunds for the operators' token alone, and
counted in the reconciliation report."""

import json

import pytest

from checkout.http import handle
from checkout.refunds.attention import NOT_OPENED_AFTER_MS, needing_operator
from tests.refund_support import owed, paystack_moves, refunded
from tests.support import make_stack

TOKEN = "ops-token-not-real"
OPERATOR = {"authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def stack():
    return make_stack(ops_token=TOKEN)


async def listed(stack) -> list[tuple[str, str]]:
    return [(r.quote_id, r.state) for r in await needing_operator(stack.db, stack.clock.now())]


class TestWhatIsListed:
    @pytest.mark.parametrize(
        ("status", "state"), [("failed", "failed"), ("needs-attention", "needs_attention")]
    )
    async def test_a_refund_paystack_failed_or_holds_is_listed(self, stack, status, state):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, status)
        assert await listed(stack) == [(quote_id, state)]

    async def test_a_refund_on_its_way_or_done_is_not(self, stack):
        await refunded(stack)
        await paystack_moves(stack, await refunded(stack), "processed")
        assert await listed(stack) == []

    async def test_a_refund_owed_and_never_opened_is_listed_once_it_is_stuck(self, stack):
        quote_id = await owed(stack)
        assert await listed(stack) == []
        stack.clock.advance(NOT_OPENED_AFTER_MS / 1000)
        assert await listed(stack) == [(quote_id, "not_opened")]
        await stack.run_jobs()
        assert await listed(stack) == []


class TestTheRoute:
    async def test_an_operator_reads_the_list(self, stack):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, "failed")
        answer = await handle(stack.app, "GET", "/ops/refunds", OPERATOR, b"")
        assert answer.status == 200
        [refund] = json.loads(answer.body)["refunds"]
        assert (refund["quoteId"], refund["state"], refund["amountKobo"]) == (quote_id, "failed", 50_000)
        assert "owner" not in refund

    @pytest.mark.parametrize(
        ("method", "headers", "status"),
        [("GET", {}, 404), ("GET", {"authorization": "Bearer wrong"}, 404), ("POST", OPERATOR, 405)],
    )
    async def test_only_an_operator_reads_it_and_only_by_get(self, stack, method, headers, status):
        assert (await handle(stack.app, method, "/ops/refunds", headers, b"")).status == status

    async def test_the_reconciliation_report_counts_them(self, stack):
        quote_id = await refunded(stack)
        await paystack_moves(stack, quote_id, "failed")
        report = (await stack.app.reconciliation.run()).view()
        assert report["refundsNeedingAnOperator"] == {
            "count": 1,
            "amountKobo": 50_000,
            "byState": {"needs_attention": 0, "failed": 1, "refused": 0, "not_opened": 0},
        }
