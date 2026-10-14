# SPDX-License-Identifier: AGPL-3.0-or-later
"""The part of JSON Schema Index's tool schemas use (type, enum, minimum, maximum, required, properties, items),
enough for the simulated Index to refuse a call as the real server would: an argument of the wrong type, one
outside its enum or its bounds, or a missing required one."""

from typing import Any

TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def _is(value: Any, kind: str) -> bool:
    if kind in ("number", "integer") and isinstance(value, bool):
        return False
    return isinstance(value, TYPES[kind])


def _bounds(value: Any, schema: dict[str, Any], where: str) -> str | None:
    if "minimum" in schema and value < schema["minimum"]:
        return f"{where} must be at least {schema['minimum']}"
    if "maximum" in schema and value > schema["maximum"]:
        return f"{where} must be at most {schema['maximum']}"
    return None


def problem(value: Any, schema: dict[str, Any], where: str = "arguments") -> str | None:
    """Why `value` is not what `schema` describes, or None when it is."""
    kind = schema.get("type")
    if kind in TYPES and not _is(value, kind):
        return f"{where} must be of type {kind}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{where} must be one of {', '.join(map(str, schema['enum']))}"
    if kind in ("number", "integer") and (found := _bounds(value, schema, where)):
        return found
    if kind == "object":
        for name in schema.get("required", []):
            if name not in value:
                return f"{where}.{name} is required"
        for name, given in value.items():
            if name in schema.get("properties", {}) and (
                found := problem(given, schema["properties"][name], f"{where}.{name}")
            ):
                return found
    if kind == "array" and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            if found := problem(item, schema["items"], f"{where}[{index}]"):
                return found
    return None
