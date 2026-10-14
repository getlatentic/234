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
VALIDATION_ONLY = frozenset({"maxLength", "minLength", "maxItems", "maxProperties", "exclusiveMinimum"})


def visibility_of(tool: dict[str, Any]) -> list[str]:
    return tool.get("_meta", {}).get(UI_KEY, {}).get("visibility") or ["model", "app"]


def card_uri_of(tool: dict[str, Any]) -> str | None:
    meta = tool.get("_meta", {})
    return meta.get(UI_KEY, {}).get("resourceUri") or meta.get(LEGACY_URI_KEY)


def takes_key(tool: dict[str, Any]) -> bool:
    return KEY_FIELD in tool.get("inputSchema", {}).get("properties", {})


def read_only(tool: dict[str, Any]) -> bool:
    return (tool.get("annotations") or {}).get("readOnlyHint") is True


def lean(schema: Any) -> Any:
    """The schema without the keywords that only the connector's own validation uses (lengths, counts, a
    positive minimum, `additionalProperties: false`): the connector still refuses what breaks them, and the
    model is not charged for them on every round. A property map is walked by its values, never its names."""
    if isinstance(schema, list):
        return [lean(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {
        key: {name: lean(spec) for name, spec in value.items()} if key == "properties" else lean(value)
        for key, value in schema.items()
        if key not in VALIDATION_ONLY and not (key == "additionalProperties" and value is False)
    }


def model_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """The schema the model is shown: the connector's, without `$schema`, without the idempotency key (the
    host supplies it, see idempotency.py) and without a property the connector marks `x-model-hidden`; a
    property named in the schema's `x-model-required` is required of the model though not of other clients;
    and `lean`. The connector's own schema is not changed."""
    return lean(_shown(tool))


def _shown(tool: dict[str, Any]) -> dict[str, Any]:
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
