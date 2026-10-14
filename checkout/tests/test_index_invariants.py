# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rules that make Index safe to offer, held apart from any one flow: the model is given none of Index's
tools and no argument that spends, nothing a model can call reaches a call that charges, a preview carries no
`confirmed`, and only the fulfilment after a person's approval ever sends one."""

import json
from pathlib import Path

import pytest

from checkout.commerce.index.purchase import Preview, Purchase
from checkout.commerce.index.sim_tool_list import TOOLS
from tests.connector_support import CONNECTORS, listed, visibility
from tests.index_support import (
    CHOWDECK,
    account,
    calls,
    connect,
    electricity,
    electricity_check,
    link_chowdeck,
    new_key,
    ok,
    press_approve,
    quote,
    text_of,
)
from tests.test_index_fulfil import charges, sim_orders

INDEX_TOOLS = {tool["name"] for tool in TOOLS}
OURS_BY_THE_SAME_NAME = {"browse_merchants", "find_items", "track_order"}
INDEX_SRC = Path(__file__).parent.parent / "src" / "checkout" / "commerce" / "index"


async def model_tools(stack):
    found = {}
    for connector in CONNECTORS:
        for name, tool in (await listed(stack, connector)).items():
            if "model" in (visibility(tool) or ["model", "app"]):
                found[(connector, name)] = tool
    return found


class TestTheModelIsGivenNoneOfIndexsTools:
    async def test_no_model_tool_is_one_of_indexs_except_the_three_names_234_uses_for_its_own(self, stack):
        names = {name for _, name in await model_tools(stack)}
        assert names & INDEX_TOOLS == OURS_BY_THE_SAME_NAME & names

    async def test_those_three_are_234s_tools_with_234s_arguments(self, stack):
        tools = await listed(stack, "merchants")
        assert sorted(tools["find_items"]["inputSchema"]["properties"]) == [
            "merchant_id",
            "offer_id",
            "query",
        ]
        assert sorted(tools["browse_merchants"]["inputSchema"]["properties"]) == ["category"]
        assert sorted(tools["track_order"]["inputSchema"]["properties"]) == ["quote_id"]

    async def test_no_model_tool_has_an_argument_that_spends_or_approves_or_reaches_index_itself(self, stack):
        forbidden = {"confirmed", "approval_token", "vendor_id", "otp", "bundle_code", "modifier_selections"}
        for (connector, name), tool in (await model_tools(stack)).items():
            found = forbidden & set(tool["inputSchema"]["properties"])
            assert not found, f"{connector}.{name} takes {found}"

    async def test_a_model_tool_called_with_confirmed_is_refused_and_nothing_reaches_index(self, stack):
        await connect(stack)
        before = len(await calls(stack))
        hostile = [
            ("create_quote", {**_quote_request(), "confirmed": True}),
            ("find_items", {"merchant_id": CHOWDECK, "confirmed": True}),
            ("track_order", {"quote_id": "qt-0123456789abcdef0123", "confirmed": True}),
            ("connect_account", {"merchant_id": CHOWDECK, "confirmed": True}),
            ("check_account", {"merchant_id": CHOWDECK, "fields": {}, "confirmed": True}),
        ]
        for tool, arguments in hostile:
            result = await account(stack, tool, **arguments)
            assert result["isError"] and "Invalid arguments" in text_of(result), tool
        assert len(await calls(stack)) == before

    async def test_the_tools_a_card_calls_are_not_the_models(self, stack):
        tools = await listed(stack, "merchants")
        for name in ("complete_connection", "send_link_code", "confirm_link_code", "disconnect_account"):
            assert visibility(tools[name]) == ["app"]
        assert visibility(tools["approve_quote"]) == ["app"]
        assert visibility(tools["connect_account"]) == ["model"]


class TestNothingChargesBeforeAnApproval:
    async def test_connecting_browsing_checking_quoting_and_declining_charge_nothing(self, stack):
        card_id = await connect(stack, merchant=CHOWDECK)
        await link_chowdeck(stack, card_id)
        await account(stack, "browse_merchants")
        await account(stack, "find_items", merchant_id=CHOWDECK, query="jollof")
        check = (await electricity_check(stack))["structuredContent"]["check_id"]
        made = await quote(stack, **electricity(check))
        food = await quote(
            stack,
            merchant_id=CHOWDECK,
            lines=[{"offer_id": "v101-i5001"}],
            fields={},
            idempotency_key=new_key(),
        )
        await account(
            stack, "decline_quote", quote_id=made["structuredContent"]["quote"]["id"],
            approval_token=made["_meta"]["approvalToken"],
        )  # fmt: skip
        assert not [c for c in await calls(stack) if c["confirmed"]]
        assert await sim_orders(stack) == [] and food

    async def test_after_the_approval_exactly_one_call_carries_confirmed(self, stack):
        await connect(stack)
        check = (await electricity_check(stack))["structuredContent"]["check_id"]
        made = await quote(stack, **electricity(check))
        ok(await press_approve(stack, made))
        assert len([c for c in await calls(stack) if c["confirmed"]]) == 1
        assert len(await charges(stack)) == 1


class TestThePreviewCannotSpend:
    async def test_a_preview_that_carries_confirmed_is_a_bug_and_is_stopped(self):
        class Boom:
            async def call(self, *_):
                raise AssertionError("reached Index")

        with pytest.raises(RuntimeError, match="confirmed"):
            await Preview(Boom()).call("order", {"confirmed": True})
        with pytest.raises(RuntimeError, match="confirmed"):
            await Preview(Boom()).call("quick_buy", {"confirmed": False})

    def test_only_a_stored_purchase_can_say_confirmed_and_only_two_modules_say_how(self):
        say = {p.name for p in INDEX_SRC.glob("*.py") if "confirmed_arguments(" in p.read_text()}
        assert say == {"purchase.py", "fulfil.py"}
        assert Purchase("food", "order", {"a": 1}, two_phase=True).confirmed_arguments() == {
            "a": 1,
            "confirmed": True,
        }
        assert (
            "confirmed"
            not in Purchase("airtime", "quick_buy", {"a": 1}, two_phase=False).confirmed_arguments()
        )

    def test_no_module_of_the_provider_builds_confirmed_into_an_argument_but_the_purchase(self):
        offenders = {
            p.name
            for p in INDEX_SRC.glob("*.py")
            if not p.name.startswith("sim") and p.name not in ("purchase.py", "outcomes.py")
            and '"confirmed"' in p.read_text()
        }  # fmt: skip
        assert offenders == set()

    def test_a_quote_remembers_the_arguments_it_was_previewed_with_and_no_confirmed(self):
        terms = Purchase("electricity", "quick_buy", {"category": "electricity"}, two_phase=True).terms()
        assert json.dumps(terms).count("confirmed") == 0


def _quote_request():
    return {
        "merchant_id": CHOWDECK,
        "lines": [{"offer_id": "v101-i5001"}],
        "fields": {},
        "idempotency_key": new_key(),
    }
