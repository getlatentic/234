# SPDX-License-Identifier: AGPL-3.0-or-later
"""The four connectors as a host sees them: JSON-RPC in, the wire shape out, and one ledger under all four."""

import json

import pytest

from tests.connector_support import (
    CARD_TOOLS,
    CONNECTORS,
    EXTRA_APP_TOOLS,
    EXTRA_VIEWS,
    MODEL_TOOLS,
    approve_args,
    listed,
    quote_of,
    text_of,
    visibility,
)
from tests.support import make_stack


class TestWhatAHostSees:
    @pytest.mark.parametrize("connector", CONNECTORS)
    async def test_offers_the_model_its_tools_and_hides_the_cards_tools(self, stack, connector):
        tools = await listed(stack, connector)
        extra = EXTRA_APP_TOOLS.get(connector, [])
        assert sorted(tools) == sorted([*MODEL_TOOLS[connector], "get_quote_status", *CARD_TOOLS, *extra])
        for name in CARD_TOOLS + extra:
            assert visibility(tools[name]) == ["app"]
        assert "_meta" not in tools["get_quote_status"]
        quote_tool = next(
            n for n in MODEL_TOOLS[connector] if n.startswith("create_") and n.endswith("_quote")
        )
        assert visibility(tools[quote_tool]) == ["model"]

    @pytest.mark.parametrize("connector", CONNECTORS)
    async def test_points_every_card_tool_at_the_connectors_own_card_resource(self, stack, connector):
        tools = await listed(stack, connector)
        views = {f"ui://{connector}/card.html", *EXTRA_VIEWS.get(connector, [])}
        uris = {t["_meta"]["ui"]["resourceUri"] for t in tools.values() if "_meta" in t}
        assert uris == views
        assert all(
            t["_meta"]["ui/resourceUri"] == t["_meta"]["ui"]["resourceUri"]
            for t in tools.values()
            if "_meta" in t
        )

    @pytest.mark.parametrize("connector", CONNECTORS)
    async def test_gives_the_model_no_field_the_schema_does_not_name(self, stack, connector):
        for tool in (await listed(stack, connector)).values():
            assert tool["inputSchema"]["type"] == "object"
            assert tool["inputSchema"]["additionalProperties"] is False

    @pytest.mark.parametrize("connector", CONNECTORS)
    async def test_no_tool_schema_needs_definitions_to_be_read(self, stack, connector):
        for tool in (await listed(stack, connector)).values():
            wire = json.dumps(tool["inputSchema"])
            assert "$ref" not in wire and "$defs" not in wire and '"title"' not in wire

    async def test_the_payment_tools_take_exactly_the_documented_fields(self, stack):
        tools = await listed(stack, "paystack-pay")
        create = tools["create_payment_quote"]["inputSchema"]["properties"]
        assert sorted(create) == sorted(
            [
                "amount_as_user_said",
                "amount_kobo",
                "description",
                "idempotency_key",
                "merchant",
                "merchant_ref",
            ]
        )
        approve = tools["approve_quote"]["inputSchema"]["properties"]
        assert sorted(approve) == sorted(
            ["approval_token", "displayed_amount_kobo", "funding", "quote_id", "readback_confirmed"]
        )

    async def test_the_food_tool_takes_items_and_quantities_only(self, stack):
        create = (await listed(stack, "food-order"))["create_food_quote"]["inputSchema"]
        assert sorted(create["properties"]) == sorted(
            ["delivery_area", "idempotency_key", "items", "note", "total_as_user_said"]
        )
        assert sorted(create["properties"]["items"]["items"]["properties"]) == ["item_id", "quantity"]

    @pytest.mark.parametrize("connector", CONNECTORS)
    async def test_tells_a_host_its_mode_as_data_for_a_banner(self, stack, connector):
        read = (await stack.mcp(connector, "resources/read", {"uri": "paystack-demo://mode"}))["result"]
        body = json.loads(read["contents"][0]["text"])
        assert body["connector"] == connector and body["simulated"] is True
        assert body["modes"]["paystack"] == "simulated"

    async def test_the_banner_names_each_connectors_own_mode(self, stack):
        async def mode(connector):
            read = (await stack.mcp(connector, "resources/read", {"uri": "paystack-demo://mode"}))["result"]
            return json.loads(read["contents"][0]["text"])

        assert (await mode("paystack-pay"))["label"] == "Simulated: no money moves"
        assert (await mode("airtime"))["modes"] == {"paystack": "simulated", "vtpass": "simulated"}
        food = await mode("food-order")
        assert food["label"] == "Simulated merchant: not Chowdeck · Simulated: no money moves"
        assert food["modes"]["merchant"] == "Simulated merchant: not Chowdeck"

    @pytest.mark.parametrize("connector", CONNECTORS)
    async def test_serves_the_card_as_an_mcp_app_resource(self, stack, connector):
        resources = (await stack.mcp(connector, "resources/list"))["result"]["resources"]
        assert sorted(r["uri"] for r in resources) == sorted(
            ["paystack-demo://mode", f"ui://{connector}/card.html", *EXTRA_VIEWS.get(connector, [])]
        )
        read = (await stack.mcp(connector, "resources/read", {"uri": f"ui://{connector}/card.html"}))[
            "result"
        ]
        content = read["contents"][0]
        assert content["mimeType"] == "text/html;profile=mcp-app"
        assert content["_meta"] == {"ui": {"prefersBorder": False}}
        assert "<html" in content["text"]

    @pytest.mark.parametrize("connector", CONNECTORS)
    async def test_tells_the_model_the_mode_and_that_it_cannot_approve(self, stack, connector):
        instructions = (await stack.mcp(connector, "initialize", {"protocolVersion": "2025-11-25"}))[
            "result"
        ]["instructions"]
        assert "Simulated: no money moves" in instructions
        assert "You cannot approve anything" in instructions
        assert "Never ask for or accept card numbers" in instructions

    async def test_the_food_connector_says_it_is_not_chowdeck(self, stack):
        instructions = (await stack.mcp("food-order", "initialize", {}))["result"]["instructions"]
        assert "Simulated merchant: not Chowdeck" in instructions and "it is not Chowdeck" in instructions


class TestOneLedgerForAllFourConnectors:
    async def test_every_connector_spends_from_the_same_daily_limit(self):
        stack = make_stack(per_payment_limit_kobo=5_000_000, daily_limit_kobo=6_000_000)
        pay = await stack.call(
            "paystack-pay", "create_payment_quote", amount_kobo=3_000_000, amount_as_user_said="30k",
            description="Rent", merchant="Landlord", idempotency_key="share-pay-000001",
        )  # fmt: skip
        send = await stack.call(
            "send-money", "create_transfer_quote", account_number="0000000000", bank_code="057",
            amount_kobo=2_000_000, amount_as_user_said="20k", idempotency_key="share-send-000001",
        )  # fmt: skip
        air = await stack.call(
            "airtime", "create_airtime_quote", network="mtn", phone="08011111111",
            amount_kobo=1_500_000, amount_as_user_said="15k", idempotency_key="share-air-0000001",
        )  # fmt: skip
        assert "isError" not in await stack.call("paystack-pay", "approve_quote", **approve_args(pay))
        assert (
            quote_of(await stack.call("send-money", "approve_quote", **approve_args(send)))["phase"]
            == "succeeded"
        )
        refused = await stack.call("airtime", "approve_quote", **approve_args(air, readback_confirmed=True))
        assert text_of(refused).startswith("LIMIT_DAILY")
        summary = await stack.ledger.budget()
        assert summary.spent_today_kobo == 5_000_000
