# SPDX-License-Identifier: AGPL-3.0-or-later
"""The stateless era of MCP (protocol revision 2026-07-28) beside the handshake era the connectors always
spoke.

A request that carries the modern version in its `_meta` and in the `MCP-Protocol-Version` header is served
on its own: no `initialize`, no session, `server/discover` to say what is spoken here, the headers checked
against the body, every result marked `resultType: "complete"`, and the cacheable ones given a `ttlMs` and a
`cacheScope`. Anything else is the earlier era, unchanged. Nothing here asks the client for anything (no
sampling, elicitation or roots), so the multi round-trip results of the revision never occur.
"""

import base64
import binascii
from collections.abc import Mapping
from typing import Any

from .registry import RESOURCE_MIME_TYPE, Connector

MODERN_VERSION = "2026-07-28"
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
SUPPORTED_VERSIONS = (MODERN_VERSION, *LEGACY_VERSIONS)
UI_EXTENSION = "io.modelcontextprotocol/ui"

VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"
SERVER_INFO_KEY = "io.modelcontextprotocol/serverInfo"

HEADER_MISMATCH = -32020
UNSUPPORTED_PROTOCOL_VERSION = -32022
INVALID_PARAMS = -32602
METHOD_NOT_FOUND = -32601

CACHED_MS = {
    "tools/list": 300_000,
    "resources/list": 300_000,
    "resources/read": 300_000,
    "server/discover": 300_000,
}
METHODS = (
    "server/discover",
    "tools/list",
    "tools/call",
    "resources/list",
    "resources/templates/list",
    "resources/read",
)
NAMED = {"tools/call": "name", "resources/read": "uri"}
SENTINEL_PREFIX, SENTINEL_SUFFIX = "=?base64?", "?="


class ModernRefusal(Exception):
    """A request the server refuses with an HTTP status and a JSON-RPC error, before it runs anything."""

    def __init__(self, status: int, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.data = status, code, message, data


def is_modern(headers: Mapping[str, str], message: Any) -> bool:
    """Whether the request is opening in the modern era: by its header or by the version in its `_meta`."""
    params = message.get("params") if isinstance(message, Mapping) else None
    meta = params.get("_meta") if isinstance(params, Mapping) else None
    named = meta.get(VERSION_KEY) if isinstance(meta, Mapping) else None
    return headers.get("mcp-protocol-version") == MODERN_VERSION or named == MODERN_VERSION


def _decoded(value: str) -> str:
    if value.startswith(SENTINEL_PREFIX) and value.endswith(SENTINEL_SUFFIX):
        try:
            return base64.b64decode(
                value[len(SENTINEL_PREFIX) : -len(SENTINEL_SUFFIX)], validate=True
            ).decode()
        except (binascii.Error, UnicodeDecodeError) as error:
            raise ModernRefusal(
                400, HEADER_MISMATCH, "Header mismatch: Mcp-Name is not valid Base64."
            ) from error
    return value


def _mismatch(text: str) -> ModernRefusal:
    return ModernRefusal(400, HEADER_MISMATCH, f"Header mismatch: {text}")


def validate(headers: Mapping[str, str], message: Mapping[str, Any]) -> None:
    """The checks a server makes before it acts on a modern request (Streamable HTTP, "Server Validation")."""
    params = message.get("params") if isinstance(message.get("params"), Mapping) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), Mapping) else {}
    version = meta.get(VERSION_KEY)
    if version is None or CAPABILITIES_KEY not in meta:
        raise ModernRefusal(
            400, INVALID_PARAMS, f"A request carries _meta {VERSION_KEY} and {CAPABILITIES_KEY}."
        )
    header = headers.get("mcp-protocol-version")
    if header != version:
        raise _mismatch(
            f"MCP-Protocol-Version header '{header}' does not match the _meta version '{version}'"
        )
    method = message.get("method")
    if headers.get("mcp-method") != method:
        raise _mismatch(
            f"Mcp-Method header '{headers.get('mcp-method')}' does not match the body method '{method}'"
        )
    if method in NAMED:
        wanted = params.get(NAMED[method])
        given = headers.get("mcp-name")
        if given is None or _decoded(given) != wanted:
            raise _mismatch(f"Mcp-Name header '{given}' does not match the body value '{wanted}'")
    if method not in METHODS:
        raise ModernRefusal(404, METHOD_NOT_FOUND, f"Method not found: {method}")


def discover(connector: Connector) -> dict[str, Any]:
    return {
        "supportedVersions": list(SUPPORTED_VERSIONS),
        "capabilities": {
            "tools": {},
            "resources": {},
            "extensions": {UI_EXTENSION: {"mimeTypes": [RESOURCE_MIME_TYPE]}},
        },
        "instructions": connector.instructions,
    }


def complete(connector: Connector, method: str, result: dict[str, Any]) -> dict[str, Any]:
    """A result of this era: complete, cacheable where the revision says so, and signed by the server."""
    meta = {
        **result.get("_meta", {}),
        SERVER_INFO_KEY: {"name": connector.name, "title": connector.title, "version": "0.1.0"},
    }
    marked = {"resultType": "complete", **result, "_meta": meta}
    if method in CACHED_MS or method == "resources/templates/list":
        marked["ttlMs"] = CACHED_MS.get(method, 300_000)
        marked["cacheScope"] = "public"
    return marked
