# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turn records built by hand, in the shape `transcript.py` makes, for the scorer's tests."""

from typing import Any

from evaluation.cases import Case, load_cases

CASES = {c.id: c for c in load_cases()}


def case(case_id: str) -> Case:
    return CASES[case_id]


def call(
    tool: str,
    server: str,
    arguments: dict[str, Any],
    *,
    error: bool = False,
    result: str = "ok",
    repeated: bool = False,
):
    return {
        "tool": tool,
        "server": server,
        "arguments": arguments,
        "is_error": error,
        "result": result,
        "repeated": repeated,
    }


def airtime(arguments: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return call("create_airtime_quote", "airtime", {"amount_as_user_said": "500", **arguments}, **kw)


def card(kobo: int = 50000) -> dict[str, Any]:
    return {
        "tool": "create_airtime_quote",
        "quote_id": "q1",
        "kind": "airtime",
        "amount_kobo": kobo,
        "merchant": "MTN",
    }


def turn(calls=(), reply: str = "", cards=(), end: str = "input_required", say: str = "") -> dict[str, Any]:
    return {
        "say": say,
        "calls": list(calls),
        "cards": list(cards),
        "reply": reply,
        "notices": [],
        "finish_reasons": ["stop"],
        "end": end,
        "latency_ms": 1000,
        "log": [],
    }
