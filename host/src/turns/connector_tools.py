# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a connector's tool declares: who may see and call it, the schema the model is shown, and the
outcome of a call."""

from dataclasses import dataclass, field
from typing import Any

from .idempotency import FIELD as KEY_FIELD

UI_KEY = "ui"
LEGACY_URI_KEY = "ui/resourceUri"
MODEL_HIDDEN = "x-model-hidden"
MODEL_REQUIRED = "x-model-required"


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


def refused(server: str, tool: str, reason: str) -> ToolOutcome:
    return ToolOutcome(server, tool, {"isError": True, "content": [{"type": "text", "text": reason}]}, None)
