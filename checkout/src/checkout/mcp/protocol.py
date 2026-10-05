# SPDX-License-Identifier: AGPL-3.0-or-later
"""MCP's JSON-RPC methods over Streamable HTTP, each request answered from itself, so any Worker
instance serves any request: the initialize-handshake era (2025-03-26 to 2025-11-25) without a
session id, and the stateless era (2026-07-28, see modern.py) for a request that opens in it."""

import json
from collections.abc import Mapping
from typing import Any

from ..events import ConnectorEvents, EventError
from . import modern
from .registry import Connector

PROTOCOL_VERSIONS = modern.LEGACY_VERSIONS
UI_EXTENSION = modern.UI_EXTENSION

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
RESOURCE_NOT_FOUND = -32002
UNSUPPORTED_PROTOCOL_VERSION = -32022
MAX_BODY = 64 * 1024


class McpError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def error_body(message_id: Any, code: int, text: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": text}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": message_id, "error": error}


def _initialize(connector: Connector, params: Mapping[str, Any], events: bool) -> dict[str, Any]:
    asked = params.get("protocolVersion")
    return {
        "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
        "capabilities": modern.capabilities(events),
        "serverInfo": {"name": connector.name, "title": connector.title, "version": "0.1.0"},
        "instructions": connector.instructions,
    }


async def _call_tool(connector: Connector, params: Mapping[str, Any]) -> dict[str, Any]:
    tool = connector.tool(str(params.get("name")))
    if tool is None:
        raise McpError(INVALID_PARAMS, f"Unknown tool: {params.get('name')}")
    return await tool.call(params.get("arguments"), connector.audit)


async def _read_resource(connector: Connector, params: Mapping[str, Any]) -> dict[str, Any]:
    resource = connector.resource(str(params.get("uri")))
    if resource is None:
        raise McpError(RESOURCE_NOT_FOUND, f"Resource not found: {params.get('uri')}")
    return await resource.contents()


async def _event(events: ConnectorEvents | None, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
    if events is None:
        raise McpError(METHOD_NOT_FOUND, f"Method not found: {method}")
    try:
        return await events.answer(method, dict(params))
    except EventError as refused:
        raise McpError(refused.code, str(refused), refused.data) from refused


async def dispatch(
    connector: Connector,
    method: str,
    params: Mapping[str, Any],
    stateless: bool = False,
    events: ConnectorEvents | None = None,
) -> dict[str, Any]:
    match method:
        case "server/discover" if stateless:
            return modern.discover(connector, events is not None)
        case "initialize":
            return _initialize(connector, params, events is not None)
        case "events/list" | "events/subscribe" | "events/unsubscribe":
            return await _event(events, method, params)
        case "ping":
            return {}
        case "tools/list":
            return {"tools": [tool.listed() for tool in connector.tools]}
        case "tools/call":
            return await _call_tool(connector, params)
        case "resources/list":
            return {"resources": [r.listed() for r in connector.resources]}
        case "resources/templates/list":
            return {"resourceTemplates": []}
        case "resources/read":
            return await _read_resource(connector, params)
        case _:
            raise McpError(METHOD_NOT_FOUND, f"Method not found: {method}")


async def answer(
    connector: Connector, message: Any, stateless: bool = False, events: ConnectorEvents | None = None
) -> dict[str, Any] | None:
    """None for a notification or a response, which get no answer. `stateless` serves the request as the
    2026-07-28 era does: marked complete, and a resource that is not there is invalid params."""
    if not isinstance(message, Mapping) or message.get("jsonrpc") != "2.0":
        return error_body(None, INVALID_REQUEST, "Not a JSON-RPC 2.0 message")
    if "id" not in message or "method" not in message:
        return None
    message_id, method = message["id"], message["method"]
    params = message.get("params") or {}
    if not isinstance(method, str) or not isinstance(params, Mapping):
        return error_body(message_id, INVALID_PARAMS, "method must be a string and params an object")
    try:
        result = await dispatch(connector, method, params, stateless, events)
    except McpError as error:
        code = INVALID_PARAMS if stateless and error.code == RESOURCE_NOT_FOUND else error.code
        return error_body(message_id, code, error.message, error.data)
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "result": modern.complete(connector, method, result) if stateless else result,
    }


def parse_body(raw: bytes) -> Any:
    if len(raw) > MAX_BODY:
        raise McpError(INVALID_REQUEST, "Request too large")
    try:
        return json.loads(raw)
    except ValueError as error:
        raise McpError(PARSE_ERROR, "Parse error") from error
