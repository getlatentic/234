# SPDX-License-Identifier: AGPL-3.0-or-later
"""The connectors driven by the official MCP clients over Streamable HTTP, as a host does: the official
Python client here, and the official TypeScript client through conformance/connectors-ts-client.mjs.
Run with `pytest -m worker`."""

import os
import subprocess
from pathlib import Path

import httpx
import pytest
from mcp import Client

from tests.worker_client import BASE_URL

pytestmark = pytest.mark.worker

ROOT = Path(__file__).resolve().parents[2]
MENU_URI = "ui://food-order/menu.html"


@pytest.fixture(autouse=True)
async def clean_ledger():
    async with httpx.AsyncClient() as http:
        await http.post(f"{BASE_URL}/test/reset")


def visibility(tool) -> list[str] | None:
    return ((tool.meta or {}).get("ui") or {}).get("visibility")


async def pay(reference_url: str) -> None:
    reference = reference_url.rsplit("/", 1)[1]
    async with httpx.AsyncClient() as http:
        await http.get(f"{BASE_URL}/sim/checkout/{reference}")
        await http.post(f"{BASE_URL}/sim/checkout/{reference}/pay")


@pytest.mark.parametrize("connector", ["paystack-pay", "send-money", "airtime", "food-order"])
async def test_lists_tools_with_their_card_metadata_and_serves_the_card(connector):
    async with Client(f"{BASE_URL}/{connector}/mcp") as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert visibility(tools["approve_quote"]) == ["app"]
        assert visibility(tools["get_quote_status"]) is None
        assert tools["approve_quote"].meta["ui"]["resourceUri"] == f"ui://{connector}/card.html"
        assert tools["approve_quote"].annotations.destructive_hint is True
        read = await client.read_resource(f"ui://{connector}/card.html")
        assert read.contents[0].mime_type == "text/html;profile=mcp-app"
        assert read.contents[0].meta == {"ui": {"prefersBorder": False}}
        assert "You cannot approve anything" in client.instructions


@pytest.mark.parametrize("mode", ["legacy", "auto", "2026-07-28"])
async def test_the_official_client_reaches_the_connectors_in_every_era(mode):
    """The handshake era, the probe that falls back or stays, and a client pinned to the stateless era, which
    never sends initialize: each lists the tools, reads the card and runs a tool."""
    async with Client(f"{BASE_URL}/paystack-pay/mcp", mode=mode) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert tools["create_payment_quote"].meta["ui"]["resourceUri"] == "ui://paystack-pay/card.html"
        read = await client.read_resource("ui://paystack-pay/card.html")
        assert read.contents[0].mime_type == "text/html;profile=mcp-app" and "<html" in read.contents[0].text
        made = await client.call_tool(
            "create_payment_quote",
            {
                "amount_kobo": 250_000,
                "amount_as_user_said": "2500",
                "description": "Lunch",
                "merchant": "Demo",
                "idempotency_key": f"py-era-{mode}-01"[:40],
            },
        )
        token = made.meta["approvalToken"]
        assert not made.is_error and len(token) == 64 and token not in made.content[0].text


async def test_an_airtime_purchase_from_quote_to_receipt():
    async with Client(f"{BASE_URL}/airtime/mcp") as client:
        made = await client.call_tool(
            "create_airtime_quote",
            {
                "network": "mtn",
                "phone": "08011111111",
                "amount_kobo": 50_000,
                "amount_as_user_said": "five hundred naira",
                "idempotency_key": "py-client-air-01",
            },
        )
        quote, token = made.structured_content["quote"], made.meta["approvalToken"]
        assert token not in made.content[0].text
        refused = await client.call_tool(
            "approve_quote",
            {"quote_id": quote["id"], "approval_token": token, "displayed_amount_kobo": 50_000},
        )
        assert refused.is_error and refused.content[0].text.startswith("READBACK_REQUIRED")
        approved = await client.call_tool(
            "approve_quote",
            {
                "quote_id": quote["id"],
                "approval_token": token,
                "displayed_amount_kobo": 50_000,
                "readback_confirmed": True,
            },
        )
        await pay(approved.structured_content["quote"]["checkoutUrl"])
        done = await client.call_tool("verify_quote", {"quote_id": quote["id"]})
        assert done.structured_content["quote"]["receipt"]["title"] == "Airtime delivered"


async def test_a_transfer_and_a_repeated_approval():
    async with Client(f"{BASE_URL}/send-money/mcp") as client:
        made = await client.call_tool(
            "create_transfer_quote",
            {
                "account_number": "0000000000",
                "bank_code": "057",
                "amount_kobo": 2_500_000,
                "amount_as_user_said": "25k",
                "idempotency_key": "py-client-send-1",
            },
        )
        quote = made.structured_content["quote"]
        args = {
            "quote_id": quote["id"],
            "approval_token": made.meta["approvalToken"],
            "displayed_amount_kobo": 2_500_000,
        }
        first = await client.call_tool("approve_quote", args)
        second = await client.call_tool("approve_quote", args)
        assert first.structured_content == second.structured_content
        assert first.structured_content["quote"]["receipt"]["title"] == "Transfer sent"


async def test_a_transfer_names_its_bank_and_the_connector_refuses_what_it_cannot_resolve():
    def args(**over):
        return {
            "account_number": "0123456789",
            "amount_kobo": 500_000,
            "amount_as_user_said": "5k",
            **over,
        }

    async with Client(f"{BASE_URL}/send-money/mcp") as client:
        made = await client.call_tool(
            "create_transfer_quote", args(bank="GTB", idempotency_key="py-bank-0001")
        )
        assert not made.is_error
        assert made.structured_content["quote"]["details"]["bankName"] == "Guaranty Trust Bank"
        for said, code in (("Acess Bank", "BANK_UNKNOWN"), ("First", "BANK_AMBIGUOUS")):
            refused = await client.call_tool(
                "create_transfer_quote", args(bank=said, idempotency_key=f"py-bank-{code.lower()}")
            )
            assert refused.is_error and refused.content[0].text.startswith(code)
        assert (
            "Access Bank"
            in (
                await client.call_tool(
                    "create_transfer_quote", args(bank="Acess Bank", idempotency_key="py-bank-near-1")
                )
            )
            .content[0]
            .text
        )
        contradicted = await client.call_tool(
            "create_transfer_quote", args(bank="GTB", bank_code="044", idempotency_key="py-bank-0002")
        )
        assert contradicted.is_error and contradicted.content[0].text.startswith("BANK_MISMATCH")
        by_code = await client.call_tool(
            "create_transfer_quote", args(bank_code="058", idempotency_key="py-bank-0003")
        )
        assert by_code.structured_content["quote"]["details"]["bankName"] == "Guaranty Trust Bank"
        tools = {t.name: t for t in (await client.list_tools()).tools}
        schema = tools["create_transfer_quote"].input_schema
        assert {"bank", "bank_code"} <= set(schema["properties"])
        assert schema["x-model-required"] == ["account_number", "bank"]
        assert schema["properties"]["bank_code"]["x-model-hidden"]


async def test_no_connector_makes_a_quote_for_one_kobo():
    tools = {
        "paystack-pay": ("create_payment_quote", {"description": "Lunch", "merchant": "Demo"}),
        "send-money": ("create_transfer_quote", {"account_number": "0123456789", "bank": "GTB"}),
        "airtime": ("create_airtime_quote", {"network": "mtn", "phone": "08011111111"}),
    }
    for connector, (tool, args) in tools.items():
        async with Client(f"{BASE_URL}/{connector}/mcp") as client:
            sent = {
                **args,
                "amount_kobo": 1,
                "amount_as_user_said": "1 kobo",
                "idempotency_key": f"py-floor-{connector}",
            }
            refused = await client.call_tool(tool, sent)
            assert refused.is_error and refused.structured_content is None
            assert refused.content[0].text.startswith("AMOUNT_TOO_SMALL: The smallest amount is ₦50."), (
                connector
            )
            at_the_floor = await client.call_tool(
                tool,
                {
                    **sent,
                    "amount_kobo": 5_000,
                    "amount_as_user_said": "50",
                    "idempotency_key": f"py-floor-ok-{connector}",
                },
            )
            assert at_the_floor.structured_content["quote"]["amount"]["display"] == "₦50", connector


async def test_a_payment_and_the_food_menu_and_a_refusal_the_model_can_read():
    async with Client(f"{BASE_URL}/food-order/mcp") as client:
        menu = await client.call_tool("search_menu", {"query": "zobo"})
        assert "\n" not in menu.content[0].text and "1 item match" in menu.content[0].text
        assert menu.structured_content["items"][0]["price_kobo"] == 80_000
        refused = await client.call_tool(
            "create_food_quote",
            {
                "items": [{"item_id": "zobo", "quantity": 1}],
                "delivery_area": "Abuja",
                "idempotency_key": "py-client-food-1",
            },
        )
        assert refused.is_error
    async with Client(f"{BASE_URL}/paystack-pay/mcp") as client:
        made = await client.call_tool(
            "create_payment_quote",
            {
                "amount_kobo": 250_000,
                "amount_as_user_said": "2500",
                "description": "Lunch",
                "merchant": "Demo",
                "idempotency_key": "py-client-pay-01",
            },
        )
        quote = made.structured_content["quote"]
        approved = await client.call_tool(
            "approve_quote",
            {
                "quote_id": quote["id"],
                "approval_token": made.meta["approvalToken"],
                "displayed_amount_kobo": 250_000,
            },
        )
        await pay(approved.structured_content["quote"]["checkoutUrl"])
        done = await client.call_tool("verify_quote", {"quote_id": quote["id"]})
        assert done.structured_content["quote"]["phase"] == "succeeded"


async def test_the_menu_view_is_listed_and_served_and_the_order_tool_is_for_cards_only():
    async with Client(f"{BASE_URL}/food-order/mcp") as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        search, order = tools["search_menu"], tools["order_from_menu"]
        assert search.meta["ui"] == {"resourceUri": MENU_URI, "visibility": ["model"]}
        assert order.meta["ui"] == {"resourceUri": MENU_URI, "visibility": ["app"]}
        assert search.meta["ui/resourceUri"] == MENU_URI
        resources = {str(r.uri): r for r in (await client.list_resources()).resources}
        assert resources[MENU_URI].mime_type == "text/html;profile=mcp-app"
        read = await client.read_resource(MENU_URI)
        assert read.contents[0].mime_type == "text/html;profile=mcp-app"
        assert read.contents[0].meta == {"ui": {"prefersBorder": False}}
        assert "order_from_menu" in read.contents[0].text and "<html" in read.contents[0].text


async def test_a_menu_card_orders_through_the_app_only_tool_and_the_server_prices_it():
    async with Client(f"{BASE_URL}/food-order/mcp") as client:
        menu = await client.call_tool("search_menu", {})
        card_id = menu.structured_content["card_id"]
        order = {
            "card_id": card_id,
            "items": [{"item_id": "zobo", "quantity": 2}, {"item_id": "beef-suya", "quantity": 1}],
            "delivery_area": "Ikeja GRA",
        }
        made = await client.call_tool("order_from_menu", order)
        quote = made.structured_content["quote"]
        assert (
            quote["amount"]["kobo"] == 2 * 80_000 + 350_000 + 120_000
            and quote["details"]["area"] == "Ikeja GRA"
        )
        assert made.meta["ui"] == {"resourceUri": "ui://food-order/card.html"}
        assert made.meta["approvalToken"] not in made.content[0].text
        again = await client.call_tool("order_from_menu", order)
        assert again.structured_content["quote"]["id"] == quote["id"]
        priced_by_the_card = await client.call_tool(
            "order_from_menu", {**order, "card_id": "f" * 32, "total_kobo": 1}
        )
        assert priced_by_the_card.is_error
        sold_out = await client.call_tool(
            "order_from_menu",
            {**order, "card_id": "e" * 32, "items": [{"item_id": "amala-ewedu", "quantity": 1}]},
        )
        assert sold_out.is_error and sold_out.content[0].text.startswith("ITEM_UNAVAILABLE")
        approved = await client.call_tool(
            "approve_quote",
            {
                "quote_id": quote["id"],
                "approval_token": made.meta["approvalToken"],
                "displayed_amount_kobo": quote["amount"]["kobo"],
            },
        )
        assert approved.structured_content["quote"]["phase"] == "awaiting_checkout"


def test_the_official_typescript_client_drives_all_four_connectors():
    env = {**os.environ, "CHECKOUT_URL": BASE_URL}
    run = subprocess.run(
        ["node", "conformance/connectors-ts-client.mjs"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "FAIL" not in run.stdout and "All checks passed." in run.stdout
