# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared by the connector tests: the wire shape of a quote made by a tool, and small readers for it."""

import itertools

_ids = itertools.count(1)

MODEL_TOOLS = {
    "paystack-pay": ["create_payment_quote"],
    "send-money": ["create_transfer_quote"],
    "airtime": ["create_airtime_quote", "create_data_quote", "list_data_plans"],
    "food-order": ["search_menu", "build_basket", "create_food_quote"],
}
CARD_TOOLS = ["approve_quote", "verify_quote", "decline_quote"]
MENU_URI = "ui://food-order/menu.html"
EXTRA_APP_TOOLS = {"send-money": ["submit_otp"], "food-order": ["order_from_menu"]}
EXTRA_VIEWS = {"food-order": [MENU_URI]}
CONNECTORS = list(MODEL_TOOLS)


def key(prefix: str) -> str:
    return f"{prefix}-{next(_ids):06d}"


def approve_args(made, **over):
    return {
        "quote_id": made["structuredContent"]["quote"]["id"],
        "approval_token": made["_meta"]["approvalToken"],
        "displayed_amount_kobo": made["structuredContent"]["quote"]["amount"]["kobo"],
        **over,
    }


def quote_of(result):
    return result["structuredContent"]["quote"]


def text_of(result) -> str:
    return result["content"][0]["text"]


async def listed(stack, connector):
    return {t["name"]: t for t in (await stack.mcp(connector, "tools/list"))["result"]["tools"]}


def visibility(tool):
    return (tool.get("_meta") or {}).get("ui", {}).get("visibility")
