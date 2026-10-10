# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared by the wallet connector tests: calls as the host makes them, for an account (the owner and the
memory header) or a visitor (the owner header alone), and an airtime quote made the same way."""

from typing import Any

from checkout.http import handle
from checkout.owner import MEMORY_OWNER_HEADER
from tests.airtime_support import quote_input
from tests.connector_support import text_of
from tests.support import ALICE, Stack

CARD_ID = "c0" * 16


def account_headers(owner: str) -> dict[str, str]:
    return {MEMORY_OWNER_HEADER: owner}


async def call(stack: Stack, connector: str, tool: str, owner: str, account: bool, **arguments: Any):
    headers = account_headers(owner) if account else {}
    params = {"name": tool, "arguments": arguments}
    return await stack.mcp(connector, "tools/call", params, owner, headers)


async def wallet(stack: Stack, tool: str, owner: str = ALICE, account: bool = True, **arguments: Any):
    """The tool's result; a refusal before the tool ran is the JSON-RPC error itself."""
    answer = await call(stack, "wallet", tool, owner, account, **arguments)
    return answer.get("result", answer)


def ok(result: dict[str, Any]) -> dict[str, Any]:
    assert "isError" not in result, text_of(result)
    return result


async def airtime_quote(stack: Stack, owner: str = ALICE, account: bool = True, **over: Any):
    made = await call(stack, "airtime", "create_airtime_quote", owner, account, **quote_input(**over))
    return ok(made["result"])


async def approve(stack: Stack, made: dict, owner: str = ALICE, account: bool = True, **over: Any):
    quote = made["structuredContent"]["quote"]
    arguments = {
        "quote_id": quote["id"],
        "approval_token": made["_meta"]["approvalToken"],
        "displayed_amount_kobo": quote["amount"]["kobo"],
        "readback_confirmed": True,
        **over,
    }
    return (await call(stack, "airtime", "approve_quote", owner, account, **arguments))["result"]


async def pay_on_stand_in(stack: Stack, checkout_url: str) -> None:
    path = checkout_url.split("://", 1)[1].partition("/")[2]
    origin = stack.app.settings.public_base_url.rstrip("/")
    await handle(stack.app, "POST", f"/{path}/pay", {"origin": origin}, b"")


async def wallets(stack: Stack) -> int:
    return await stack.count("wallet")
