# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a connector offers an MCP host, in MCP Apps' terms: model tools that show a card,
app-only tools the card calls, plain tools, and the `ui://` resources that render the cards.

The tool list a host reads is built from here, so a tool's visibility is declared once.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from ..audit import Audit
from ..card_guard import assert_no_card_data
from ..errors import DomainError

RESOURCE_MIME_TYPE = "text/html;profile=mcp-app"
LEGACY_RESOURCE_URI_KEY = "ui/resourceUri"
MODEL_ONLY = ("model",)
APP_ONLY = ("app",)

ToolResult = dict[str, Any]
Handler = Callable[[Any], Awaitable[ToolResult]]


def _inline_refs(schema: Any, defs: dict[str, Any]) -> Any:
    """Replaces each `$ref` with the definition it names, so no schema needs `$defs` to be read."""
    if isinstance(schema, list):
        return [_inline_refs(item, defs) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        target = defs[schema["$ref"].removeprefix("#/$defs/")]
        rest = {k: v for k, v in schema.items() if k != "$ref"}
        return _inline_refs({**target, **rest}, defs)
    return {k: _inline_refs(v, defs) for k, v in schema.items()}


def plain_schema(schema: Any) -> Any:
    """Pydantic's JSON Schema without what gateways stumble on: `$defs`, titles, and `anyOf [X, null]`
    for an optional field, which becomes X (the field is simply not required)."""
    if isinstance(schema, dict) and "$defs" in schema:
        defs = schema["$defs"]
        return plain_schema(_inline_refs({k: v for k, v in schema.items() if k != "$defs"}, defs))
    if isinstance(schema, list):
        return [plain_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    options = schema.get("anyOf")
    if isinstance(options, list) and len(options) == 2:
        kept = [o for o in options if o != {"type": "null"}]
        if len(kept) == 1:
            rest = {k: v for k, v in schema.items() if k not in ("anyOf", "default")}
            return plain_schema({**kept[0], **rest})
    return {k: plain_schema(v) for k, v in schema.items() if k != "title" or isinstance(v, dict)}


INTERNAL_MESSAGE = (
    "INTERNAL: The server hit an unexpected error. Check the quote's status before trying again."
)


def failed(text: str) -> ToolResult:
    return {"content": [{"type": "text", "text": text}], "isError": True}


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    arguments: type[BaseModel]
    run: Handler
    resource_uri: str | None = None
    visibility: tuple[str, ...] | None = None
    annotations: dict[str, Any] = field(default_factory=dict)

    def listed(self) -> dict[str, Any]:
        listing: dict[str, Any] = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": plain_schema(self.arguments.model_json_schema()),
        }
        if self.annotations:
            listing["annotations"] = self.annotations
        ui: dict[str, Any] = {}
        if self.resource_uri:
            ui["resourceUri"] = self.resource_uri
        if self.visibility:
            ui["visibility"] = list(self.visibility)
        if ui:
            meta: dict[str, Any] = {"ui": ui}
            if self.resource_uri:
                meta[LEGACY_RESOURCE_URI_KEY] = self.resource_uri
            listing["_meta"] = meta
        return listing

    async def call(self, arguments: Any, audit: Audit) -> ToolResult:
        """Arguments it cannot read, a refusal, and a card number are tool errors the caller can correct,
        not protocol errors. An unexpected failure is logged and never shown to the caller."""
        try:
            assert_no_card_data(arguments, "input")
            parsed = self.arguments.model_validate(arguments or {})
            result = await self.run(parsed)
            content = {"content": result.get("content"), "structuredContent": result.get("structuredContent")}
            assert_no_card_data(content, "output")
            return result
        except ValidationError as error:
            details = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
            return failed(f"Invalid arguments for {self.name}: {details}")
        except DomainError as error:
            if error.code == "CARD_DATA_REFUSED":
                audit.log("guard.card_data_refused", tool=self.name)
            return failed(f"{error.code}: {error.message}")
        except Exception as error:
            audit.log("tool.error", tool=self.name, message=str(error))
            return failed(INTERNAL_MESSAGE)


@dataclass(frozen=True)
class UiResource:
    uri: str
    name: str
    description: str
    read: Callable[[], Awaitable[str]]
    meta_ui: dict[str, Any] = field(default_factory=lambda: {"prefersBorder": False})

    def listed(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": RESOURCE_MIME_TYPE,
            "_meta": {"ui": self.meta_ui},
        }

    async def contents(self) -> dict[str, Any]:
        return {
            "contents": [
                {
                    "uri": self.uri,
                    "mimeType": RESOURCE_MIME_TYPE,
                    "text": await self.read(),
                    "_meta": {"ui": self.meta_ui},
                }
            ]
        }


@dataclass(frozen=True)
class JsonResource:
    """A plain JSON resource, such as the connector's mode banner."""

    uri: str
    name: str
    description: str
    read: Callable[[], Awaitable[dict[str, Any]]]

    def listed(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": "application/json",
        }

    async def contents(self) -> dict[str, Any]:
        text = json.dumps(await self.read())
        return {"contents": [{"uri": self.uri, "mimeType": "application/json", "text": text}]}


@dataclass(frozen=True)
class Connector:
    """One MCP server: a name, instructions the model reads, tools and resources."""

    name: str
    title: str
    instructions: str
    tools: tuple[Tool, ...]
    resources: tuple[UiResource | JsonResource, ...]
    audit: Audit

    def tool(self, name: str) -> Tool | None:
        return next((t for t in self.tools if t.name == name), None)

    def resource(self, uri: str) -> UiResource | JsonResource | None:
        return next((r for r in self.resources if r.uri == uri), None)
