# SPDX-License-Identifier: AGPL-3.0-or-later
"""The host's view of the connectors: which tools the model may see, which a card may call, and where
each call goes. A tool is never in both hands unless its server said so."""

import base64
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from . import trace
from .idempotency import FIELD as KEY_FIELD

OWNER_HEADER = "x-ledger-owner"
GROUP_HEADER = "x-ledger-group"
TASK_HEADER = "x-task-id"
ACCOUNT_META = "com.getlatentic.234/account"
MEMORY_OWNER_HEADER = "x-memory-owner"
MEMORY_SERVER = "memory"
SEPARATOR = "__"
PROTOCOL_VERSION = "2025-11-25"
MIME_TYPE = "text/html;profile=mcp-app"
UI_KEY = "ui"
_OWNER = re.compile(r"[0-9a-f]{32}")
LEGACY_URI_KEY = "ui/resourceUri"
MODEL_HIDDEN = "x-model-hidden"
MODEL_REQUIRED = "x-model-required"


class HubError(Exception):
    """A request the host refuses because of who is asking or what they asked for."""


def visibility_of(tool: dict[str, Any]) -> list[str]:
    return tool.get("_meta", {}).get(UI_KEY, {}).get("visibility") or ["model", "app"]


def card_uri_of(tool: dict[str, Any]) -> str | None:
    meta = tool.get("_meta", {})
    return meta.get(UI_KEY, {}).get("resourceUri") or meta.get(LEGACY_URI_KEY)


def takes_key(tool: dict[str, Any]) -> bool:
    return KEY_FIELD in tool.get("inputSchema", {}).get("properties", {})


def read_only(tool: dict[str, Any]) -> bool:
    return (tool.get("annotations") or {}).get("readOnlyHint") is True


def model_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """The schema the model is shown: the connector's, without `$schema`, without the idempotency key (the
    host supplies it, see idempotency.py) and without a property the connector marks `x-model-hidden`; a
    property named in the schema's `x-model-required` is required of the model though not of other clients.
    The connector's own schema is not changed."""
    schema = {k: v for k, v in tool["inputSchema"].items() if k not in ("$schema", MODEL_REQUIRED)}
    properties = schema.get("properties")
    if properties is None:
        return schema
    hidden = {name for name, spec in properties.items() if spec.get(MODEL_HIDDEN)} | {KEY_FIELD}
    schema["properties"] = {k: v for k, v in properties.items() if k not in hidden}
    required = [*schema.get("required", []), *tool["inputSchema"].get(MODEL_REQUIRED, [])]
    if "required" in schema or MODEL_REQUIRED in tool["inputSchema"]:
        schema["required"] = [name for name in dict.fromkeys(required) if name not in hidden]
    return schema


def text_of(result: dict[str, Any]) -> str:
    return "\n".join(b.get("text", "") for b in result.get("content", []) if b.get("type") == "text").strip()


@dataclass(frozen=True)
class CardPage:
    """A card's document and the `_meta.ui` its resource declares (csp, permissions, domain, prefersBorder),
    read from the content item of `resources/read`, or from the listing entry when the content has none."""

    html: str
    ui: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolOutcome:
    server: str
    tool: str
    result: dict[str, Any]
    card_uri: str | None

    @property
    def text(self) -> str:
        return text_of(self.result)

    @property
    def is_error(self) -> bool:
        return bool(self.result.get("isError"))


def _owner_key(owner: str) -> str:
    if not _OWNER.fullmatch(owner):
        raise HubError("A tool call names whose money it touches, as 32 hex characters.")
    return owner


def refused(server: str, tool: str, reason: str) -> ToolOutcome:
    return ToolOutcome(server, tool, {"isError": True, "content": [{"type": "text", "text": reason}]}, None)


_payer_group: ContextVar[str] = ContextVar("payer_group", default="")


@contextmanager
def paying_as(group: str) -> Iterator[None]:
    """The connector calls made inside the block name `group` as their payer group ('' for none): the people
    one outside agent speaks for, whose spend the ledger caps together (pact/identity.py)."""
    token = _payer_group.set(group)
    try:
        yield
    finally:
        _payer_group.reset(token)


class McpHttp:
    """A minimal MCP client over Streamable HTTP: JSON-RPC requests, JSON answers."""

    def __init__(self, url: str, client: httpx.AsyncClient, token: str = "") -> None:
        self.url = url
        self._client = client
        self._token = token
        self._ids = 0
        self._session: str | None = None
        self._ready = False

    async def _post(
        self, body: dict[str, Any], owner: str | None = None, notes: bool = False
    ) -> httpx.Response:
        headers = {"accept": "application/json, text/event-stream", "mcp-protocol-version": PROTOCOL_VERSION}
        if owner is not None:
            headers[OWNER_HEADER] = owner
            if notes:
                headers[MEMORY_OWNER_HEADER] = owner
            if group := _payer_group.get():
                headers[GROUP_HEADER] = group
            if task := trace.current().task:
                headers[TASK_HEADER] = task
        if self._session:
            headers["mcp-session-id"] = self._session
        if self._token:
            headers["authorization"] = f"Bearer {self._token}"
        return await self._client.post(self.url, json=body, headers=headers)

    async def relay(self, body: bytes, passed_on: dict[str, str], owner: str, notes: bool) -> httpx.Response:
        """Another client's MCP message, sent as it came with only `passed_on` (the MCP protocol version, the
        session and the last event id) of its headers; the owner and the token are this client's own."""
        headers = {
            **passed_on,
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            OWNER_HEADER: _owner_key(owner),
        }
        if notes:
            headers[MEMORY_OWNER_HEADER] = owner
        if self._token:
            headers["authorization"] = f"Bearer {self._token}"
        return await self._client.post(self.url, content=body, headers=headers)

    async def _initialize(self) -> None:
        capabilities = {
            "extensions": {"io.modelcontextprotocol/ui": {"mimeTypes": ["text/html;profile=mcp-app"]}}
        }
        answer = await self._post(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": capabilities,
                    "clientInfo": {"name": "checkout-host", "version": "0.1.0"},
                },
            }
        )
        answer.raise_for_status()
        self._session = answer.headers.get("mcp-session-id")
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._ready = True

    async def request(
        self, method: str, params: dict[str, Any] | None = None, owner: str | None = None, notes: bool = False
    ) -> dict[str, Any]:
        """`owner` is whose money a tool call touches; it travels in a header of its own that only this
        client sets, never in the arguments or `_meta`, which a card or the model can shape. `notes`: the
        call is to the memory connector, which is also told the owner in its own header."""
        if not self._ready:
            await self._initialize()
        self._ids += 1
        response = await self._post(
            {"jsonrpc": "2.0", "id": self._ids, "method": method, "params": params or {}}, owner, notes
        )
        body = _answer(response, method)
        if "error" in body:
            raise HubError(f"{method}: {body['error']['message']}")
        return body["result"]


def _answer(response: httpx.Response, method: str) -> dict[str, Any]:
    """The JSON-RPC answer, or HubError when the connector sent none: a connector restarted mid-request
    answers with an empty body or an error page, which is a connector that could not be reached."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or not ("result" in body or "error" in body):
        raise HubError(f"{method}: the connector answered {response.status_code} with no JSON-RPC reply.")
    return body


def _html_of(content: dict[str, Any]) -> str:
    if isinstance(content.get("text"), str):
        return content["text"]
    if isinstance(content.get("blob"), str):
        return base64.b64decode(content["blob"]).decode()
    raise HubError("The card has no content.")


def _ui_meta(item: dict[str, Any]) -> dict[str, Any]:
    ui = (item.get("_meta") or {}).get("ui")
    return ui if isinstance(ui, dict) else {}


class Server(Protocol):
    """What the hub asks of a connector: a remote one over Streamable HTTP (McpHttp), or one the host serves
    itself (turns/reach/server.py)."""

    async def request(
        self, method: str, params: dict[str, Any] | None = None, owner: str | None = None, notes: bool = False
    ) -> dict[str, Any]: ...

    async def relay(
        self, body: bytes, passed_on: dict[str, str], owner: str, notes: bool
    ) -> httpx.Response: ...


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
        """A connector the host serves itself is also told whether `owner` is a signed-in account."""
        params: dict[str, Any] = {"name": name, "arguments": arguments}
        if server in self._local:
            params["_meta"] = {ACCOUNT_META: account}
        return await self._server(server).request(
            "tools/call", params, _owner_key(owner), notes=server == MEMORY_SERVER
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
        self, server: str, name: str, arguments: dict[str, Any], owner: str
    ) -> dict[str, Any]:
        """A card's own call. It reaches only the server that served the card, and only tools that
        server offers to cards."""
        tool = await self._find(server, name)
        if "app" not in visibility_of(tool):
            raise HubError(f"{name} is not available to cards.")
        return await self._tool_call(server, name, arguments, owner)

    async def ping(self, server: str) -> None:
        """MCP's own liveness request, after the handshake: the connector is reachable and answering."""
        await self._server(server).request("ping")

    async def subscribe(self, server: str, params: dict[str, Any], owner: str) -> None:
        """An MCP events subscription made as `owner`, so its events are that owner's quotes only."""
        await self._server(server).request("events/subscribe", params, _owner_key(owner))

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
