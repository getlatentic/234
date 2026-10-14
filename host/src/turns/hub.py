# SPDX-License-Identifier: AGPL-3.0-or-later
"""The host's view of the connectors: which tools the model may see, which a card may call, and where
each call goes. A tool is never in both hands unless its server said so."""

import base64
from typing import Any

import httpx

from .connector_tools import (
    CardPage,
    ToolOutcome,
    card_uri_of,
    model_schema,
    read_only,
    refused,
    takes_key,
    visibility_of,
)
from .idempotency import FIELD as KEY_FIELD
from .mcp_http import HubError, McpHttp, Server, owner_key

ACCOUNT_META = "com.getlatentic.234/account"
MEMORY_SERVER = "memory"
WALLET_SERVER = "wallet"
MERCHANTS_SERVER = "merchants"
SEPARATOR = "__"
MIME_TYPE = "text/html;profile=mcp-app"


def _html_of(content: dict[str, Any]) -> str:
    if isinstance(content.get("text"), str):
        return content["text"]
    if isinstance(content.get("blob"), str):
        return base64.b64decode(content["blob"]).decode()
    raise HubError("The card has no content.")


def _ui_meta(item: dict[str, Any]) -> dict[str, Any]:
    ui = (item.get("_meta") or {}).get("ui")
    return ui if isinstance(ui, dict) else {}


class Hub:
    def __init__(
        self,
        endpoints: dict[str, str],
        client: httpx.AsyncClient,
        token: str = "",
        local: dict[str, Server] | None = None,
    ) -> None:
        """`local`: connectors the host serves itself, by name, offered after the remote ones."""
        remote = {name: McpHttp(url, client, token) for name, url in endpoints.items()}
        self._servers: dict[str, Server] = dict(remote)
        self._servers.update(local or {})
        self._local = frozenset(local or {})
        self._tools: dict[str, list[dict[str, Any]]] = {}

    def _server(self, name: str) -> Server:
        if name not in self._servers:
            raise HubError(f"There is no connector {name}.")
        return self._servers[name]

    async def tools(self, server: str) -> list[dict[str, Any]]:
        if server not in self._tools:
            self._tools[server] = (await self._server(server).request("tools/list"))["tools"]
        return self._tools[server]

    async def _find(self, server: str, name: str) -> dict[str, Any]:
        tool = next((t for t in await self.tools(server) if t["name"] == name), None)
        if tool is None:
            raise HubError(f"There is no tool {name} on {server}.")
        return tool

    async def model_tools(self) -> list[dict[str, Any]]:
        """OpenAI-style tool definitions: model-visible tools only, named by connector."""
        offered = []
        for server in self._servers:
            for tool in await self.tools(server):
                if "model" not in visibility_of(tool):
                    continue
                offered.append(
                    {
                        "type": "function",
                        "function": {
                            "name": f"{server}{SEPARATOR}{tool['name']}",
                            "description": f"[{server}] {tool.get('description') or tool['name']}",
                            "parameters": model_schema(tool),
                        },
                    }
                )
        return offered

    async def _tool_call(
        self, server: str, name: str, arguments: dict[str, Any], owner: str, account: bool = False
    ) -> dict[str, Any]:
        """A connector is told in the memory header that `owner` is a signed-in account (the wallet and an
        approval card need to know); one the host serves itself is told in `_meta`. The memory connector
        is always sent it: the host lets only an account's calls reach memory."""
        params: dict[str, Any] = {"name": name, "arguments": arguments}
        if server in self._local:
            params["_meta"] = {ACCOUNT_META: account}
        return await self._server(server).request(
            "tools/call", params, owner_key(owner), notes=account or server == MEMORY_SERVER
        )

    async def keyed(self, qualified: str) -> bool:
        """Whether the tool makes a request the ledger remembers by its idempotency key."""
        server, _, name = qualified.partition(SEPARATOR)
        try:
            return takes_key(await self._find(server, name))
        except HubError:
            return False

    async def repeatable(self, qualified: str) -> bool:
        """Whether running it again does no harm: it only reads, or the ledger remembers it by its key."""
        server, _, name = qualified.partition(SEPARATOR)
        try:
            tool = await self._find(server, name)
        except HubError:
            return False
        return takes_key(tool) or read_only(tool)

    async def read_only(self, qualified: str) -> bool:
        server, _, name = qualified.partition(SEPARATOR)
        try:
            return read_only(await self._find(server, name))
        except HubError:
            return False

    async def status_tools(self, server: str) -> list[str]:
        """The tools of `server` the model may call to see how things stand: model-visible, read-only."""
        try:
            listed = await self.tools(server)
        except HubError, httpx.HTTPError:
            return []
        return [
            f"{server}{SEPARATOR}{t['name']}" for t in listed if "model" in visibility_of(t) and read_only(t)
        ]

    async def call_model_tool(
        self, qualified: str, arguments: dict[str, Any], owner: str, key: str, account: bool = False
    ) -> ToolOutcome:
        """`key` is the idempotency key of this call. A tool that takes one is given it in place of
        whatever the model sent; a tool that takes none is not sent one."""
        server, _, name = qualified.partition(SEPARATOR)
        try:
            tool = await self._find(server, name)
        except HubError as reason:
            return refused(server, name, str(reason))
        if "model" not in visibility_of(tool):
            return refused(server, name, f"{name} is not available to the model.")
        if takes_key(tool):
            arguments = {**arguments, KEY_FIELD: key}
        result = await self._tool_call(server, name, arguments, owner, account)
        return ToolOutcome(server, name, result, card_uri_of(tool))

    async def call_app_tool(
        self, server: str, name: str, arguments: dict[str, Any], owner: str, account: bool = False
    ) -> dict[str, Any]:
        """A card's own call. It reaches only the server that served the card, and only tools that
        server offers to cards."""
        tool = await self._find(server, name)
        if "app" not in visibility_of(tool):
            raise HubError(f"{name} is not available to cards.")
        return await self._tool_call(server, name, arguments, owner, account)

    async def ping(self, server: str) -> None:
        """MCP's own liveness request, after the handshake: the connector is reachable and answering."""
        await self._server(server).request("ping")

    async def subscribe(self, server: str, params: dict[str, Any], owner: str) -> None:
        """An MCP events subscription made as `owner`, so its events are that owner's quotes only."""
        await self._server(server).request("events/subscribe", params, owner_key(owner))

    async def relay(
        self, server: str, body: bytes, passed_on: dict[str, str], owner: str, notes: bool
    ) -> httpx.Response:
        return await self._server(server).relay(body, passed_on, owner, notes)

    async def read_card(self, server: str, uri: str) -> CardPage:
        connector = self._server(server)
        listed = {
            r["uri"]: r
            for r in (await connector.request("resources/list"))["resources"]
            if r["uri"].startswith("ui://")
        }
        if uri not in listed:
            raise HubError(f"{server} declares no card at {uri}.")
        contents = (await connector.request("resources/read", {"uri": uri}))["contents"]
        if not contents:
            raise HubError("The card has no content.")
        content = contents[0]
        if content.get("mimeType") != MIME_TYPE:
            raise HubError(f"A card is {MIME_TYPE}.")
        return CardPage(_html_of(content), _ui_meta(content) or _ui_meta(listed[uri]))


def build_hub(
    mcp_url: str,
    connectors: tuple[str, ...],
    client: httpx.AsyncClient,
    token: str = "",
    local: dict[str, Server] | None = None,
) -> Hub:
    return Hub({name: f"{mcp_url}/{name}/mcp" for name in connectors}, client, token, local)
