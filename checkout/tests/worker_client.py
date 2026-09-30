# SPDX-License-Identifier: AGPL-3.0-or-later
"""A minimal MCP client for tests against a running Worker (`pywrangler dev`): JSON-RPC over HTTP."""

import itertools
import os
from typing import Any

import httpx

BASE_URL = os.environ.get("CHECKOUT_URL", "http://localhost:8787")
_ids = itertools.count(1)


ALICE = "a1" * 16
BOB = "b0" * 16
OWNER_HEADER = "x-ledger-owner"


class Mcp:
    """A JSON-RPC client for one connector; `owner` is the key the host would name in the owner header."""

    def __init__(
        self, http: httpx.AsyncClient, connector: str = "paystack-pay", owner: str | None = None
    ) -> None:
        self.http = http
        self.url = f"{BASE_URL}/{connector}/mcp"
        self.owner = owner

    def as_owner(self, owner: str, connector: str | None = None) -> Mcp:
        return Mcp(self.http, connector or self.url.rsplit("/", 2)[1], owner)

    async def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        body = {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params or {}}
        headers = {"accept": "application/json"}
        if self.owner is not None:
            headers[OWNER_HEADER] = self.owner
        response = await self.http.post(self.url, json=body, headers=headers)
        return response.json()

    async def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        answer = await self.rpc("tools/call", {"name": tool, "arguments": arguments})
        return answer["result"]


def quote_args(
    amount_kobo: int = 250_000, said: str = "₦2,500", key: str = "lunch-000001", **more: Any
) -> dict[str, Any]:
    return {
        "amount_kobo": amount_kobo,
        "amount_as_user_said": said,
        "description": "Lunch",
        "merchant": "Demo Kitchen",
        "idempotency_key": key,
        **more,
    }


def quote_of(result: dict[str, Any]) -> dict[str, Any]:
    return result["structuredContent"]["quote"]
