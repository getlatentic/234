# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Worker's HTTP surface, free of the Workers runtime so tests can call it directly:
one MCP endpoint per connector, the simulated Paystack checkout page, and test routes."""

import hmac
from collections.abc import Mapping
from contextlib import ExitStack
from typing import Any

from .app import App
from .config import MEMORY_CONNECTOR
from .mcp import modern
from .mcp.protocol import (
    INVALID_REQUEST,
    UNSUPPORTED_PROTOCOL_VERSION,
    McpError,
    answer,
    error_body,
    parse_body,
)
from .owner import MEMORY_OWNER_HEADER, OWNER_HEADER, acting_for, is_owner_key, remembering_for
from .responses import HttpResponse, json_response
from .sim_checkout import handle_checkout
from .testing_routes import handle_test


def _bearer_is_valid(app: App, headers: dict[str, str]) -> bool:
    """With no token configured the endpoint is open (local development and tests)."""
    expected = app.settings.mcp_token
    if expected is None:
        return True
    given = headers.get("authorization", "").removeprefix("Bearer ").strip()
    return hmac.compare_digest(given.encode(), expected.encode())


def _message_id(message: Any) -> Any:
    return message.get("id") if isinstance(message, Mapping) else None


def _owner_of(app: App, headers: dict[str, str], message: Any) -> str | None:
    """The owner the host named in the owner header, and from nowhere else: not the body, not `_meta`,
    not the arguments. A malformed one is refused; a tool call with none is refused when the
    configuration requires one."""
    given = headers.get(OWNER_HEADER)
    if given is not None and not is_owner_key(given):
        raise McpError(INVALID_REQUEST, "The owner header is not an owner key.")
    calls_a_tool = isinstance(message, Mapping) and message.get("method") == "tools/call"
    if given is None and calls_a_tool and app.settings.require_owner:
        raise McpError(INVALID_REQUEST, "A tool call must say whose it is.")
    return given


def _checked_key(given: str | None, name: str) -> str | None:
    if given is None or is_owner_key(given):
        return given
    raise McpError(INVALID_REQUEST, f"The {name} header is not an owner key.")


def _memory_owner_of(headers: dict[str, str], message: Any, connector: str) -> str | None:
    """The owner of the notes, from the memory header and from nowhere else. A malformed one is refused, and
    so is a call to the memory connector that has none: memory is for signed-in accounts."""
    given = _checked_key(headers.get(MEMORY_OWNER_HEADER), "memory owner")
    calls_a_tool = isinstance(message, Mapping) and message.get("method") == "tools/call"
    if given is None and calls_a_tool and connector == MEMORY_CONNECTOR:
        raise McpError(INVALID_REQUEST, "Memory is for signed-in accounts.")
    return given


def _screened(message: Any, headers: dict[str, str], stateless: bool) -> HttpResponse | None:
    version = headers.get("mcp-protocol-version")
    if version and version not in modern.SUPPORTED_VERSIONS:
        body = error_body(
            _message_id(message),
            UNSUPPORTED_PROTOCOL_VERSION,
            f"Unsupported protocol version: {version}",
            {"supported": list(modern.SUPPORTED_VERSIONS), "requested": version},
        )
        return json_response(body, 400)
    if isinstance(message, list):
        return json_response(error_body(None, INVALID_REQUEST, "Batches are not part of MCP"), 400)
    if stateless and isinstance(message, Mapping) and "id" in message and "method" in message:
        try:
            modern.validate(headers, message)
        except modern.ModernRefusal as refusal:
            return json_response(
                error_body(message["id"], refusal.code, refusal.message, refusal.data), refusal.status
            )
    return None


async def handle_mcp(
    app: App, connector_name: str, method: str, headers: dict[str, str], raw: bytes
) -> HttpResponse:
    if not _bearer_is_valid(app, headers):
        return HttpResponse(401, "Unauthorized", {"www-authenticate": "Bearer"})
    connector = app.connectors.get(connector_name)
    if connector is None:
        return HttpResponse(404, "No such connector")
    origin = headers.get("origin")
    if origin is not None and origin not in app.settings.mcp_allowed_origins:
        return json_response(
            error_body(None, INVALID_REQUEST, "This origin may not call the connectors."), 403
        )
    if method != "POST":
        return HttpResponse(405, "", {"allow": "POST"})
    try:
        message = parse_body(raw)
    except McpError as error:
        status = 413 if error.code == -32600 else 400
        return json_response(error_body(None, error.code, error.message), status)
    stateless = modern.is_modern(headers, message)
    if refusal := _screened(message, headers, stateless):
        return refusal
    try:
        owner = _owner_of(app, headers, message)
        memory_owner = _memory_owner_of(headers, message, connector_name)
    except McpError as error:
        return json_response(error_body(_message_id(message), error.code, error.message), 400)
    with ExitStack() as acting:
        if owner is not None:
            acting.enter_context(acting_for(owner))
        if memory_owner is not None:
            acting.enter_context(remembering_for(memory_owner))
        response = await answer(connector, message, stateless)
    return HttpResponse(202) if response is None else json_response(response)


async def handle(
    app: App, method: str, path: str, headers: dict[str, str], raw: bytes, query: str = ""
) -> HttpResponse:
    parts = path.strip("/").split("/")
    if parts == ["health"]:
        return json_response({"ok": True})
    if len(parts) == 2 and parts[1] == "mcp":
        return await handle_mcp(app, parts[0], method, headers, raw)
    if parts[0] == "sim" and len(parts) >= 3 and parts[1] == "checkout":
        return await handle_checkout(app, method, path, headers, query)
    if parts[0] == "test" and app.settings.enable_test_routes:
        return await handle_test(app, method, path, query)
    return HttpResponse(404, "Not found")
