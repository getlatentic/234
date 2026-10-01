# SPDX-License-Identifier: AGPL-3.0-or-later
"""A chat's event log as one record per turn. Pure: the runner feeds it the events it read, the scorer reads
the records, and `report.py` feeds it nothing because the records are stored.

A turn record is a plain dict, so it is stored as it is:

    say, calls, cards, reply, notices, finish_reasons, end, latency_ms, log

`calls` are the model's tool calls (tool, server, arguments, is_error, result, repeated); `cards` are the
approval, menu or memory cards the chat got, as a line each; `log` is the turn in order, for a reader.
"""

from typing import Any

REPEATED_PREFIX = "Not made again: "
RESULT_CHARS = 600
IGNORED = {"text", "card_state", "card_message", "card_context"}


def _card(payload: dict[str, Any]) -> dict[str, Any]:
    data = (payload.get("result") or {}).get("structuredContent") or {}
    quote = data.get("quote") or {}
    amount = quote.get("amount") or {}
    memory = data.get("memory")
    card = {
        "tool": payload.get("tool"),
        "quote_id": quote.get("id"),
        "kind": (quote.get("details") or {}).get("kind"),
        "amount_kobo": amount.get("kobo"),
        "merchant": quote.get("merchant"),
        "menu_items": len(data.get("items") or []) or None,
    }
    return {**card, "memory_op": memory.get("op"), "memory_title": memory.get("title")} if memory else card


def _call(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload["result_text"]
    return {
        "tool": payload["tool"],
        "server": payload["server"],
        "arguments": payload["arguments"],
        "is_error": bool(payload["is_error"]),
        "result": result[:RESULT_CHARS],
        "repeated": result.startswith(REPEATED_PREFIX),
    }


def _entry(event: dict[str, Any]) -> dict[str, Any] | None:
    payload = event["payload"]
    match event["type"]:
        case "assistant":
            calls = [c["name"] for c in payload.get("tool_calls", [])]
            return {
                "t": "assistant",
                "text": payload["text"],
                "finish_reason": payload["finish_reason"],
                "calls": calls,
            }
        case "tool":
            return {"t": "tool", **_call(payload)}
        case "card":
            return {"t": "card", **_card(payload)}
        case "notice":
            return {"t": "notice", "level": payload.get("level"), "text": payload["text"]}
    return None


def _record(say: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    log = [entry for event in events if (entry := _entry(event))]
    finished = next((e for e in reversed(events) if e["type"] == "turn.finished"), None)
    started = events[0]["at"] if events else 0
    return {
        "say": say,
        "calls": [{k: v for k, v in e.items() if k != "t"} for e in log if e["t"] == "tool"],
        "cards": [{k: v for k, v in e.items() if k != "t"} for e in log if e["t"] == "card"],
        "reply": " ".join(e["text"].strip() for e in log if e["t"] == "assistant" and e["text"].strip()),
        "notices": [e["text"] for e in log if e["t"] == "notice"],
        "finish_reasons": [e["finish_reason"] for e in log if e["t"] == "assistant"],
        "end": finished["payload"]["reason"] if finished else "unfinished",
        "latency_ms": finished["at"] - started if finished else None,
        "log": log,
    }


def turns_of(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per `user` event: the events from it up to the next one."""
    starts = [i for i, e in enumerate(events) if e["type"] == "user"]
    bounds = [*starts, len(events)]
    return [
        _record(events[s]["payload"]["text"], [e for e in events[s:end] if e["type"] not in IGNORED])
        for s, end in zip(starts, bounds[1:], strict=True)
    ]
