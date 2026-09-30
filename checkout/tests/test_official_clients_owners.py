# SPDX-License-Identifier: AGPL-3.0-or-later
"""One owner's money is out of another's reach through the official MCP clients, on the running Worker and
its local D1: the Python client here, the TypeScript client in conformance/connectors-ts-client.mjs. The
owner is what the chat host names in the owner header. Run with `pytest -m worker`."""

import httpx
import pytest
from mcp import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from tests.worker_client import ALICE, BASE_URL, BOB, OWNER_HEADER

pytestmark = pytest.mark.worker

PAY = f"{BASE_URL}/paystack-pay/mcp"


@pytest.fixture(autouse=True)
async def clean_ledger():
    async with httpx.AsyncClient() as http:
        await http.post(f"{BASE_URL}/test/reset")


def acting_as(owner: str, url: str = PAY) -> Client:
    """The official client with the owner header on every request it sends, as the host's client has."""
    return Client(
        streamable_http_client(url, http_client=create_mcp_http_client(headers={OWNER_HEADER: owner}))
    )


def quote_args(key: str, kobo: int = 3_000_000, said: str = "30k") -> dict:
    return {
        "amount_kobo": kobo,
        "amount_as_user_said": said,
        "description": "Lunch",
        "merchant": "Demo",
        "idempotency_key": key,
    }


def approval(made, **over) -> dict:
    quote = made.structured_content["quote"]
    return {
        "quote_id": quote["id"],
        "approval_token": made.meta["approvalToken"],
        "displayed_amount_kobo": quote["amount"]["kobo"],
        **over,
    }


async def test_another_owner_cannot_read_verify_approve_or_decline_a_quote_it_knows_the_id_of():
    async with acting_as(ALICE) as alice, acting_as(BOB) as bob:
        made = await alice.call_tool("create_payment_quote", quote_args("py-owner-quote-1"))
        quote_id = made.structured_content["quote"]["id"]
        for tool, args in (
            ("get_quote_status", {"quote_id": quote_id}),
            ("verify_quote", {"quote_id": quote_id}),
            ("approve_quote", approval(made)),
            ("decline_quote", {"quote_id": quote_id, "approval_token": made.meta["approvalToken"]}),
        ):
            refused = await bob.call_tool(tool, args)
            assert refused.is_error and refused.content[0].text.startswith("QUOTE_NOT_FOUND"), tool
            assert refused.structured_content is None
        untouched = await alice.call_tool("get_quote_status", {"quote_id": quote_id})
        assert untouched.structured_content["quote"]["phase"] == "awaiting_approval"


async def test_each_owner_has_a_daily_limit_of_their_own_and_a_refusal_reads_in_one_line():
    async with acting_as(ALICE) as alice, acting_as(BOB) as bob:
        for i in range(3):
            made = await alice.call_tool("create_payment_quote", quote_args(f"py-alice-day-{i}"))
            assert not (await alice.call_tool("approve_quote", approval(made))).is_error
        over = await alice.call_tool("create_payment_quote", quote_args("py-alice-day-9"))
        assert over.is_error
        assert over.content[0].text == (
            "LIMIT_DAILY: ₦30,000 would take today's approved total above the daily limit of ₦100,000 "
            "(₦10,000 left today)."
        )
        made = await bob.call_tool("create_payment_quote", quote_args("py-bob-day-1"))
        assert made.structured_content["quote"]["limits"]["remainingToday"] == "₦100,000"
        assert not (await bob.call_tool("approve_quote", approval(made))).is_error


async def test_two_owners_can_use_the_same_idempotency_key():
    async with acting_as(ALICE) as alice, acting_as(BOB) as bob:
        first = await alice.call_tool("create_payment_quote", quote_args("py-shared-key-1", 250_000, "2.5k"))
        second = await bob.call_tool("create_payment_quote", quote_args("py-shared-key-1", 300_000, "3k"))
        assert not first.is_error and not second.is_error
        assert first.structured_content["quote"]["id"] != second.structured_content["quote"]["id"]
        assert second.structured_content["quote"]["amount"]["kobo"] == 300_000


async def test_a_paid_quote_settles_only_for_its_own_owner():
    async with acting_as(ALICE) as alice, acting_as(BOB) as bob:
        made = await alice.call_tool("create_payment_quote", quote_args("py-owner-pay-1", 250_000, "2.5k"))
        approved = await alice.call_tool("approve_quote", approval(made))
        reference = approved.structured_content["quote"]["checkoutUrl"].rsplit("/", 1)[1]
        async with httpx.AsyncClient() as http:
            await http.get(f"{BASE_URL}/sim/checkout/{reference}")
            await http.post(f"{BASE_URL}/sim/checkout/{reference}/pay")
        quote_id = made.structured_content["quote"]["id"]
        assert (await bob.call_tool("verify_quote", {"quote_id": quote_id})).is_error
        done = await alice.call_tool("verify_quote", {"quote_id": quote_id})
        assert done.structured_content["quote"]["phase"] == "succeeded"


async def test_a_card_only_tool_and_the_menu_order_are_scoped_the_same_way():
    order = {"card_id": "c" * 32, "items": [{"item_id": "zobo", "quantity": 1}], "delivery_area": "Yaba"}
    food = f"{BASE_URL}/food-order/mcp"
    async with acting_as(ALICE, food) as alice, acting_as(BOB, food) as bob:
        theirs = await alice.call_tool("order_from_menu", order)
        mine = await bob.call_tool("order_from_menu", order)
        assert theirs.structured_content["quote"]["id"] != mine.structured_content["quote"]["id"]
        assert theirs.meta["approvalToken"] != mine.meta["approvalToken"]
        stolen = await bob.call_tool("approve_quote", approval(theirs))
        assert stolen.is_error and stolen.content[0].text.startswith("QUOTE_NOT_FOUND")


async def test_a_malformed_owner_is_refused_by_the_worker():
    async with httpx.AsyncClient() as http:
        for bad in ("legacy", ALICE.upper(), ALICE + "0"):
            reply = await http.post(
                PAY,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={OWNER_HEADER: bad, "accept": "application/json"},
            )
            assert reply.status_code == 400
            assert reply.json()["error"]["message"] == "The owner header is not an owner key."


async def test_an_owner_named_in_the_body_instead_of_the_header_is_ignored():
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "create_payment_quote",
            "arguments": quote_args("py-body-owner-1"),
            "_meta": {"owner": BOB},
        },
    }
    async with httpx.AsyncClient() as http:
        made = (await http.post(PAY, json=body, headers={"accept": "application/json"})).json()["result"]
        assert not made.get("isError")
        quote_id = made["structuredContent"]["quote"]["id"]
        async with acting_as(BOB) as bob:
            assert (await bob.call_tool("get_quote_status", {"quote_id": quote_id})).is_error
