# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated VTpass through the real client, ported from the TypeScript demo's simulator.test.ts."""

import pytest

from checkout.config import SimulatorSettings
from checkout.vtpass.api import AirtimeOrder, DataOrder
from tests.support import make_stack


def vtpass_of(**simulator):
    stack = make_stack(simulator=SimulatorSettings(**simulator))
    return stack, stack.app.contexts["airtime"].vtpass


def order(phone: str, request_id: str, **over) -> AirtimeOrder:
    return AirtimeOrder(
        **{"request_id": request_id, "network": "mtn", "phone": phone, "amount_kobo": 50_000, **over}
    )


async def test_delivers_to_the_documented_success_number():
    _, api = vtpass_of()
    outcome = await api.buy_airtime(order("08011111111", "202609291405success01"))
    assert (outcome.status, outcome.code) == ("delivered", "000")
    assert (await api.requery("202609291405success01")).status == "delivered"


@pytest.mark.parametrize(
    "phone",
    ["07031234567", "08031234567", "08051234567", "08091234567", "09021234567", "09151234567", "07011234567"],
    ids=["MTN 0703", "MTN 0803", "Glo 0805", "9mobile 0809", "Airtel 0902", "Glo 0915", "Airtel 0701"],
)
async def test_delivers_to_any_valid_nigerian_mobile_number_unlike_the_real_sandbox(phone):
    _, api = vtpass_of()
    outcome = await api.buy_airtime(order(phone, "202609291405anynumber01"))
    assert (outcome.status, outcome.code) == ("delivered", "000")
    assert (await api.requery("202609291405anynumber01")).status == "delivered"


@pytest.mark.parametrize("phone", ["12345", "0803123456", "080312345678", "06031234567", "abcdefghijk"])
async def test_fails_a_number_that_is_not_a_valid_nigerian_mobile(phone):
    _, api = vtpass_of()
    outcome = await api.buy_airtime(order(phone, "202609291405badnumber01"))
    assert (outcome.status, outcome.code) == ("failed", "016")


async def test_fails_on_the_simulator_only_failure_number_so_the_failed_path_can_be_shown():
    _, api = vtpass_of()
    outcome = await api.buy_airtime(order("100000000000", "202609291405failed001"))
    assert (outcome.status, outcome.code) == ("failed", "016")
    assert (await api.requery("202609291405failed001")).status == "failed"


async def test_stays_pending_on_the_pending_number_then_delivers_after_the_wait():
    stack, api = vtpass_of(pending_seconds=20)
    assert (await api.buy_airtime(order("201000000000", "202609291405pending01"))).status == "pending"
    stack.clock.advance(10)
    assert (await api.requery("202609291405pending01")).status == "pending"
    stack.clock.advance(10)
    assert (await api.requery("202609291405pending01")).status == "delivered"


@pytest.mark.parametrize(
    ("phone", "request_id"),
    [
        ("500000000000", "202609291405unexpect01"),
        ("400000000000", "202609291405noreply001"),
        ("300000000000", "202609291405timeout001"),
    ],
)
async def test_reads_an_unexpected_reply_no_reply_and_a_timeout_all_as_pending(phone, request_id):
    _, api = vtpass_of()
    assert (await api.buy_airtime(order(phone, request_id))).status == "pending"


async def test_recognises_a_repeated_request_id_and_an_unknown_one():
    _, api = vtpass_of()
    await api.buy_airtime(order("08011111111", "202609291405repeat0001"))
    repeated = await api.buy_airtime(order("08011111111", "202609291405repeat0001"))
    assert (repeated.status, repeated.code) == ("pending", "014")
    assert (await api.requery("nothing-like-this")).unknown_request


async def test_refuses_an_amount_below_the_minimum():
    _, api = vtpass_of()
    outcome = await api.buy_airtime(order("08011111111", "202609291405belowmin001", amount_kobo=4_000))
    assert (outcome.status, outcome.code) == ("failed", "013")


async def test_buys_data_with_a_plan_and_lists_plans():
    _, api = vtpass_of()
    plans = await api.data_plans("mtn")
    assert (plans[0].code, plans[0].name, plans[0].amount_kobo) == (
        "mtn-10mb-100",
        "N100 100MB - 24 hrs",
        10_000,
    )
    outcome = await api.buy_data(
        DataOrder("202609291405data0000001", "mtn", "08011111111", "mtn-10mb-100", 10_000)
    )
    assert outcome.status == "delivered"


@pytest.mark.parametrize("network", ["airtel", "glo", "9mobile"])
async def test_labels_sample_plans_for_the_other_networks_as_simulated(network):
    _, api = vtpass_of()
    plans = await api.data_plans(network)
    assert plans and all("simulated" in plan.name for plan in plans)


async def test_answers_as_the_real_sandbox_does_for_an_account_it_will_not_accept():
    _, api = vtpass_of(vtpass_rejects_credentials=True)
    access = await api.check_access()
    assert (access.ok, access.reason) == (False, "VTpass refused this account's credentials (HTTP 401).")
    assert (await api.buy_airtime(order("08011111111", "202609291405refused0001"))).status == "failed"
    assert await api.data_plans("mtn"), "the plan list needs no credentials, as on the real sandbox"


async def test_refuses_a_request_without_the_keys_with_the_code_the_sandbox_used():
    from checkout.vtpass.sim import VtpassSimulator
    from checkout.vtpass.sim_store import VtpassSimStore

    stack, _ = vtpass_of()
    simulator = VtpassSimulator(VtpassSimStore(stack.db), stack.clock)
    reply = await simulator.send(
        "POST", "https://sandbox.vtpass.com/api/pay", headers={}, body="{}", timeout_seconds=1
    )
    assert (reply.status, reply.body) == (401, '{"code": "087", "message": "INVALID CREDENTIALS"}')
