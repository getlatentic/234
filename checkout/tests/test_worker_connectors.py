# SPDX-License-Identifier: AGPL-3.0-or-later
"""The four connectors through the running Worker and its local D1 (workerd, Pyodide). Run with
`pytest -m worker`. Each concurrency test fires its calls together with asyncio.gather, so they
interleave at every D1 await, as real requests do."""

import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from tests.worker_client import BASE_URL, Mcp, quote_args, quote_of

pytestmark = pytest.mark.worker

PROBE_PORT = int(os.environ.get("PROBE_PORT", "8889"))


async def summary(worker):
    return (await worker.http.get(f"{BASE_URL}/test/summary")).json()


def approve_args(made, **over):
    quote = quote_of(made)
    return {
        "quote_id": quote["id"],
        "approval_token": made["_meta"]["approvalToken"],
        "displayed_amount_kobo": quote["amount"]["kobo"],
        **over,
    }


async def pay(worker, url, outcome="pay"):
    reference = url.rsplit("/", 1)[1]
    await worker.http.get(f"{BASE_URL}/sim/checkout/{reference}")
    await worker.http.post(f"{BASE_URL}/sim/checkout/{reference}/{outcome}")


@pytest.fixture
def connectors(worker):
    return {name: Mcp(worker.http, name) for name in ("paystack-pay", "send-money", "airtime", "food-order")}


async def make_airtime(connectors, key, phone="08011111111"):
    return await connectors["airtime"].call(
        "create_airtime_quote", network="mtn", phone=phone, amount_kobo=50_000,
        amount_as_user_said="₦500", idempotency_key=key,
    )  # fmt: skip


class TestEachConnectorEndToEnd:
    async def test_airtime_from_quote_to_receipt(self, worker, connectors):
        air = connectors["airtime"]
        made = await make_airtime(connectors, "e2e-airtime-0001")
        approved = await air.call("approve_quote", **approve_args(made, readback_confirmed=True))
        await pay(worker, quote_of(approved)["checkoutUrl"])
        done = quote_of(await air.call("verify_quote", quote_id=quote_of(made)["id"]))
        assert (done["phase"], done["receipt"]["title"]) == ("succeeded", "Airtime delivered")

    async def test_a_pending_airtime_order_finishes_after_the_simulators_wait(self, worker, connectors):
        air = connectors["airtime"]
        made = await make_airtime(connectors, "e2e-airtime-0002", phone="201000000000")
        approved = await air.call("approve_quote", **approve_args(made, readback_confirmed=True))
        await pay(worker, quote_of(approved)["checkoutUrl"])
        first = quote_of(await air.call("verify_quote", quote_id=quote_of(made)["id"]))
        assert (first["phase"], first["poll"]) == ("processing", True)
        for _ in range(30):
            await asyncio.sleep(1)
            view = quote_of(await air.call("verify_quote", quote_id=quote_of(made)["id"]))
            if view["phase"] == "succeeded":
                break
        assert view["phase"] == "succeeded"
        assert (await summary(worker))["vtpassOrders"] == 1

    async def test_a_transfer_is_sent_after_approval(self, connectors):
        send = connectors["send-money"]
        made = await send.call(
            "create_transfer_quote", account_number="0000000000", bank_code="057", amount_kobo=2_500_000,
            amount_as_user_said="25k", narration="Rent", idempotency_key="e2e-transfer-0001",
        )  # fmt: skip
        done = quote_of(await send.call("approve_quote", **approve_args(made)))
        assert (done["phase"], done["receipt"]["title"]) == ("succeeded", "Transfer sent")

    async def test_a_food_order_follows_the_kitchen_clock_to_delivery(self, worker, connectors):
        food = connectors["food-order"]
        made = await food.call(
            "create_food_quote", items=[{"item_id": "zobo", "quantity": 1}], delivery_area="Yaba",
            idempotency_key="e2e-food-00001",
        )  # fmt: skip
        approved = await food.call("approve_quote", **approve_args(made))
        await pay(worker, quote_of(approved)["checkoutUrl"])
        view = quote_of(await food.call("verify_quote", quote_id=quote_of(made)["id"]))
        assert (view["phase"], view["tracking"]["current"]) == ("processing", 0)


class TestUnderConcurrency:
    async def test_vtpass_is_ordered_from_once_however_many_verify_together(self, worker, connectors):
        air = connectors["airtime"]
        made = await make_airtime(connectors, "race-airtime-0001")
        approved = await air.call("approve_quote", **approve_args(made, readback_confirmed=True))
        await pay(worker, quote_of(approved)["checkoutUrl"])
        results = await asyncio.gather(
            *[air.call("verify_quote", quote_id=quote_of(made)["id"]) for _ in range(25)]
        )
        assert not any(r.get("isError") for r in results)
        state = await summary(worker)
        assert state["vtpassOrders"] == 1
        assert state["byState"]["settled"]["n"] == 1
        assert (await air.call("verify_quote", quote_id=quote_of(made)["id"]))["structuredContent"]["quote"][
            "phase"
        ] == "succeeded"

    async def test_a_transfer_is_sent_once_however_many_approve_together(self, worker, connectors):
        send = connectors["send-money"]
        made = await send.call(
            "create_transfer_quote", account_number="0000000000", bank_code="057", amount_kobo=2_500_000,
            amount_as_user_said="25k", idempotency_key="race-transfer-0001",
        )  # fmt: skip
        results = await asyncio.gather(*[send.call("approve_quote", **approve_args(made)) for _ in range(25)])
        assert not any(r.get("isError") for r in results)
        state = await summary(worker)
        assert state["transfers"] == 1
        assert state["claimedEvents"] == {quote_of(made)["id"]: 1}
        final = quote_of(await send.call("verify_quote", quote_id=quote_of(made)["id"]))
        assert final["phase"] == "succeeded"

    async def test_the_kitchen_takes_the_order_once_however_many_check_together(self, worker, connectors):
        food = connectors["food-order"]
        made = await food.call(
            "create_food_quote", items=[{"item_id": "zobo", "quantity": 2}], delivery_area="Yaba",
            idempotency_key="race-food-000001",
        )  # fmt: skip
        approved = await food.call("approve_quote", **approve_args(made))
        await pay(worker, quote_of(approved)["checkoutUrl"])
        results = await asyncio.gather(
            *[food.call("verify_quote", quote_id=quote_of(made)["id"]) for _ in range(20)]
        )
        assert {quote_of(r)["tracking"]["current"] for r in results} <= {0, 1}
        state = await summary(worker)
        assert state["byState"]["approved"]["n"] == 1

    async def test_the_daily_limit_holds_across_all_four_connectors_at_once(self, worker, connectors):
        """Eight quotes of N30,000 spread over the four connectors, each approved by three callers at once:
        the limit of N100,000 leaves room for exactly three."""
        quotes = [
            (name, await thirty_thousand(connectors[name], name, f"share-{name}-{i}"))
            for i in range(2)
            for name in connectors
        ]
        assert all("isError" not in made for _, made in quotes)
        calls = [
            connectors[name].call("approve_quote", **approve_args(made, readback_confirmed=True))
            for name, made in quotes
            for _ in range(3)
        ]
        await asyncio.gather(*calls)
        state = await summary(worker)
        approved = state["byState"].get("approved", {"n": 0, "kobo": 0})
        settled = state["byState"].get("settled", {"n": 0, "kobo": 0})
        assert approved["n"] + settled["n"] == 3
        assert state["spentTodayKobo"] == approved["kobo"] + settled["kobo"] == 9_000_000
        assert all(n == 1 for n in state["claimedEvents"].values())

    async def test_the_control_read_then_write_approval_overspends_across_connectors(
        self, worker, connectors
    ):
        overspent = 0
        for round_ in range(6):
            await worker.http.post(f"{BASE_URL}/test/reset")
            made = [
                await thirty_thousand(connectors[name], name, f"naive-{round_}-{name}-{i}")
                for i in range(4)
                for name in ("paystack-pay", "airtime")
            ]
            await asyncio.gather(
                *[worker.http.post(f"{BASE_URL}/test/naive-approve/{quote_of(m)['id']}") for m in made]
            )
            state = await summary(worker)
            if state["byState"].get("approved", {"kobo": 0})["kobo"] > state["dailyLimitKobo"]:
                overspent += 1
        assert overspent >= 1, "the naive approval never overspent, so the load is not concurrent enough"


async def thirty_thousand(connector, name, key):
    """A quote of exactly N30,000 from any connector; the keys differ per call."""
    key = f"{key}-{name}"[:64].ljust(8, "0")
    match name:
        case "paystack-pay":
            return await connector.call("create_payment_quote", **quote_args(3_000_000, "₦30,000", key))
        case "send-money":
            return await connector.call(
                "create_transfer_quote",
                account_number="0000000000",
                bank_code="057",
                amount_kobo=3_000_000,
                amount_as_user_said="30k",
                idempotency_key=key,
            )
        case "airtime":
            return await connector.call(
                "create_airtime_quote",
                network="mtn",
                phone="08011111111",
                amount_kobo=3_000_000,
                amount_as_user_said="30k",
                idempotency_key=key,
            )
        case _:
            items = [
                {"item_id": "catfish-pepper-soup", "quantity": 4},
                {"item_id": "fried-rice-dodo", "quantity": 1},
            ]
            return await connector.call(
                "create_food_quote", items=items, delivery_area="Yaba", idempotency_key=key
            )


class _Probe(BaseHTTPRequestHandler):
    seen: ClassVar[list[str]] = []

    def do_GET(self):
        _Probe.seen.append(self.headers.get("X-Probe", ""))
        body = b'{"hello":"worker"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


async def test_the_workers_fetch_transport_carries_a_call_and_reports_an_unreachable_host(worker):
    server = HTTPServer(("127.0.0.1", PROBE_PORT), _Probe)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        reply = (
            await worker.http.get(
                f"{BASE_URL}/test/fetch-probe", params={"url": f"http://localhost:{PROBE_PORT}/x"}
            )
        ).json()
    finally:
        server.shutdown()
    assert reply == {"status": 200, "body": '{"hello":"worker"}', "contentType": "application/json"}
    assert _Probe.seen == ["1"], "the header the transport sent reached the server"
    down = (
        await worker.http.get(f"{BASE_URL}/test/fetch-probe", params={"url": "http://localhost:8898/x"})
    ).json()
    assert "transportError" in down


async def test_the_probe_route_refuses_a_non_local_address(worker):
    refused = await worker.http.get(
        f"{BASE_URL}/test/fetch-probe", params={"url": "https://api.paystack.co/"}
    )
    assert refused.status_code == 400
