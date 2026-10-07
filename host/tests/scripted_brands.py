# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the scripted model does with 234's `brands` connector (turns/reach/), the way a model that follows
the prompt would: "ask <brand> <request>" sends the request to that Brand ("skyline" is Skyline Airways);
after the sign-in card says the person signed in, it sends the last request again; and it reports the Brand's
reply as the tool gave it. Used by fake_model.py."""

import re
from typing import Any

ASK = re.compile(r"^ask (?P<brand>\w+) (?P<text>.+)$", re.I)
SIGNED_IN = re.compile(r"^\[card message\] I've signed in with (?P<name>.+)\.$")
TOOL = "brands__message_brand"
BRAND_IDS = {"skyline": "skyline-airways"}


def _offered(tools: list[dict[str, Any]]) -> bool:
    return any(t["function"]["name"] == TOOL for t in tools)


def _content(message: dict[str, Any]) -> str:
    return message["content"] if isinstance(message.get("content"), str) else ""


def _last_ask(messages: list[dict[str, Any]]) -> re.Match | None:
    for message in reversed(messages):
        if message["role"] == "user" and (found := ASK.match(_content(message))):
            return found
    return None


def _call(found: re.Match) -> dict[str, Any]:
    brand = BRAND_IDS.get(found["brand"].lower(), found["brand"].lower())
    return {"tool": TOOL, "arguments": {"brand": brand, "text": found["text"]}}


def answer(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _offered(tools):
        return None
    last = messages[-1]
    if last["role"] == "tool":
        called = next((m for m in reversed(messages[:-1]) if m["role"] == "assistant"), None)
        names = [c["function"]["name"] for c in (called or {}).get("tool_calls") or []]
        return {"text": _content(last)} if TOOL in names else None
    content = _content(last)
    if last["role"] == "user" and (found := ASK.match(content)):
        return _call(found)
    if last["role"] == "user" and SIGNED_IN.match(content) and (asked := _last_ask(messages)):
        return _call(asked)
    return None
