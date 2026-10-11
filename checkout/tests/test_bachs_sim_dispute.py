# SPDX-License-Identifier: AGPL-3.0-or-later
"""A chargeback on the simulated Bachs (sim_bachs_dispute.py), raised and decided through the test route and
delivered, signed, through the same /hooks/bachs code a real one reaches; the route exists only with the test
routes on."""

import json

import pytest

from checkout.http import handle
from tests.support import ALICE, make_stack
from tests.topup_support import SECRET, balance, started, topups


@pytest.fixture
def stack():
    return make_stack(approval_secret=SECRET)


async def paid_on_the_page(stack, amount: int = 250_000):
    topup = await started(stack, amount)
    await handle(stack.app, "POST", f"/sim/bachs/{topup.provider_ref}/pay", {}, b"")
    return topup


async def dispute(stack, checkout_id: str, query: str = ""):
    return await handle(stack.app, "POST", f"/test/bachs-dispute/{checkout_id}", {}, b"", query)


async def test_a_dispute_raised_on_a_paid_charge_holds_and_is_decided(stack):
    topup = await paid_on_the_page(stack)
    paid = await topups(stack).get(topup.id)
    assert paid is not None and paid.charge_id == f"ch_{topup.provider_ref.removeprefix('chk_')}"
    raised = await dispute(stack, topup.provider_ref)
    assert raised.status == 200 and json.loads(raised.body)["hookStatus"] == 200
    assert await balance(stack) == 0
    await dispute(stack, topup.provider_ref, "event=dispute.updated&status=won")
    assert await balance(stack) == 250_000
    rows = await stack.rows("SELECT kind FROM wallet_entry WHERE owner = ? ORDER BY seq", ALICE)
    assert [row["kind"] for row in rows] == ["fund", "dispute", "dispute_back"]


async def test_a_dispute_for_part_of_the_charge(stack):
    topup = await paid_on_the_page(stack)
    await dispute(stack, topup.provider_ref, "amount=1000.00")
    assert await balance(stack) == 150_000


async def test_only_a_paid_checkout_and_a_known_status_can_be_disputed(stack):
    topup = await started(stack)
    assert (await dispute(stack, topup.provider_ref)).status == 404
    paid = await paid_on_the_page(stack)
    assert (await dispute(stack, paid.provider_ref, "status=refunded")).status == 400
    assert (await dispute(stack, paid.provider_ref, "amount=lots")).status == 400


async def test_without_the_test_routes_there_is_no_dispute_route():
    stack = make_stack(approval_secret=SECRET, enable_test_routes=False)
    topup = await paid_on_the_page(stack)
    assert (await dispute(stack, topup.provider_ref)).status == 404
    assert await balance(stack) == 250_000
