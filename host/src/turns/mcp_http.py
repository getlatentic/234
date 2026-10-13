# SPDX-License-Identifier: AGPL-3.0-or-later
"""The host's MCP client for a remote connector: JSON-RPC over Streamable HTTP, with the headers that name
whose money a call touches."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Protocol

import httpx

from . import trace

OWNER_HEADER = "x-ledger-owner"
GROUP_HEADER = "x-ledger-group"
TASK_HEADER = "x-task-id"
MEMORY_OWNER_HEADER = "x-memory-owner"
PROTOCOL_VERSION = "2025-11-25"
_OWNER = re.compile(r"[0-9a-f]{32}")


class HubError(Exception):
    """A request the host refuses because of who is asking or what they asked for."""


def owner_key(owner: str) -> str:
    if not _OWNER.fullmatch(owner):
        raise HubError("A tool call names whose money it touches, as 32 hex characters.")
    return owner


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
            OWNER_HEADER: owner_key(owner),
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


class Server(Protocol):
    """What the hub asks of a connector: a remote one over Streamable HTTP (McpHttp), or one the host serves
    itself (turns/reach/server.py)."""

    async def request(
        self, method: str, params: dict[str, Any] | None = None, owner: str | None = None, notes: bool = False
    ) -> dict[str, Any]: ...

    async def relay(
        self, body: bytes, passed_on: dict[str, str], owner: str, notes: bool
    ) -> httpx.Response: ...
