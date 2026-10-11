# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the connectors record about the wallet (metrics.py): one data point for each wallet movement, with
its kind, outcome and amount; never the owner or any id; and recording that fails never fails the movement."""

import json

import pytest

from checkout.http import handle
from checkout.metrics import Metrics, metrics_of
from checkout.owner import DEFAULT_OWNER
from tests.airtime_support import code_of, quote_input
from tests.support import ALICE, make_stack
from tests.withdrawal_support import approved, funded, paystack_event, set_transfer, started


class Sink:
    def __init__(self, broken: bool = False) -> None:
        self.points: list[tuple[str, tuple, tuple]] = []
        self.broken = broken

    def write(self, kind, blobs, doubles):
        if self.broken:
            raise RuntimeError("the binding is gone")
        self.points.append((kind, tuple(blobs), tuple(doubles)))

    def wallet(self) -> list[tuple[str, str, float]]:
        return [(*blobs, doubles[0]) for kind, blobs, doubles in self.points if kind == "wallet"]


@pytest.fixture
def sink() -> Sink:
    return Sink()


@pytest.fixture
def stack(sink):
    return make_stack(metrics=Metrics(sink), ops_token="ops-token-not-real")


async def _from_wallet(stack, amount: int = 50_000, **over):
    issued = await stack.airtime.create_airtime_quote(**quote_input(amount_kobo=amount, **over))
    return await stack.airtime.approve(
        issued.quote["id"], issued.approval_token, amount, True, funding="wallet"
    )


async def test_funding_and_spending_are_a_data_point_each(stack, sink):
    journal = stack.app.withdrawals.journal
    await journal.credit(DEFAULT_OWNER, "fund", 100_000, "top-up-1")
    await journal.credit(DEFAULT_OWNER, "fund", 100_000, "top-up-1")
    await _from_wallet(stack)
    await code_of(_from_wallet(stack, 60_000, amount_as_user_said="₦600"))
    assert sink.wallet() == [
        ("fund", "ok", 100_000),
        ("fund", "repeat", 100_000),
        ("spend", "ok", 50_000),
        ("spend", "refused", 60_000),
    ]


async def test_a_release_and_a_refund_are_recorded(stack, sink):
    await stack.app.withdrawals.journal.credit(DEFAULT_OWNER, "fund", 200_000, "top-up-1")
    issued = await stack.airtime.create_airtime_quote(**quote_input())
    stack.clock.advance(601)
    await code_of(
        stack.airtime.approve(issued.quote["id"], issued.approval_token, 50_000, True, funding="wallet")
    )
    await _from_wallet(stack, phone="100000000000")
    assert ("release", "ok", 50_000) in sink.wallet()
    assert ("refund", "ok", 50_000) in sink.wallet()


async def test_a_withdrawal_and_its_money_back_are_recorded(stack, sink):
    await funded(stack)
    withdrawal = await approved(stack, await started(stack, 2_000_000))
    await approved(stack, withdrawal)
    await set_transfer(stack, withdrawal, "reversed")
    await paystack_event(stack, withdrawal, "transfer.reversed")
    await stack.run_jobs()
    points = sink.wallet()
    assert [p for p in points if p[0] == "withdraw"] == [
        ("withdraw", "ok", 2_000_000),
        ("withdraw", "repeat", 2_000_000),
    ]
    assert ("withdraw_back", "ok", 2_000_000) in points


async def test_a_correction_is_recorded(stack, sink):
    await funded(stack, 5_000_000)
    for direction, amount in (("credit", 100_000), ("debit", 4_000_000), ("debit", 4_000_000)):
        await _correct(stack, f"fix-{direction}-{amount}", direction, amount)
    await _correct(stack, "fix-credit-100000", "credit", 100_000)
    assert sink.wallet()[-4:] == [
        ("adjust", "ok", 100_000),
        ("adjust", "ok", 4_000_000),
        ("adjust", "repeat", 4_000_000),
        ("adjust", "repeat", 100_000),
    ]
    await _correct(stack, "fix-short", "debit", 2_000_000)
    assert sink.wallet()[-1] == ("adjust", "refused", 2_000_000)


async def _correct(stack, correction_id: str, direction: str, amount: int) -> None:
    sent = {"correction_id": correction_id, "owner": ALICE, "direction": direction, "amount_kobo": amount,
            "reason": "a correction", "operator": "ada"}  # fmt: skip
    headers = {"authorization": "Bearer ops-token-not-real"}
    await handle(stack.app, "POST", "/ops/wallet/adjust", headers, json.dumps(sent).encode())


async def test_no_point_names_the_owner_or_any_id(stack, sink):
    await funded(stack)
    withdrawal = await approved(stack, await started(stack))
    await stack.app.withdrawals.journal.credit(DEFAULT_OWNER, "fund", 100_000, "top-up-secret-ref")
    issued = await stack.airtime.create_airtime_quote(**quote_input())
    await stack.airtime.approve(issued.quote["id"], issued.approval_token, 50_000, True, funding="wallet")
    written = json.dumps(sink.points)
    assert sink.points
    for private in (ALICE, DEFAULT_OWNER, withdrawal.id, issued.quote["id"], "top-up-secret-ref"):
        assert private not in written


async def test_recording_that_fails_never_fails_the_movement():
    stack = make_stack(metrics=Metrics(Sink(broken=True)))
    journal = stack.app.withdrawals.journal
    assert await journal.credit(DEFAULT_OWNER, "fund", 100_000, "top-up-1") is not None
    assert await journal.balance(DEFAULT_OWNER) == 100_000


def test_a_worker_without_the_binding_records_nothing():
    class Env:
        pass

    metrics_of(Env()).wallet("fund", "ok", 100)
