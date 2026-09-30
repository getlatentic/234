# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sends the starters and a few complete requests to the host and reports what a real model did with each:
whether it called a quote tool with a field the person never gave, whether it asked instead, whether it made
the right quote (and how many quote cards the chat got), whether it still sends an idempotency key it is not
offered, and how every round ended (`finish_reason`). A script for the owner, not a test: it makes
real model calls. usage: tools/real-model.sh probe [DRAWS_PER_PROMPT] [PROMPT_SUBSTRING]
PROBE_LOG=file.jsonl keeps every draw."""

import asyncio
import collections
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from turns.calls import REPEATED

from .worker_client import Visitor, finished, until

QUOTE_TOOLS = frozenset(
    {
        "create_airtime_quote",
        "create_data_quote",
        "create_transfer_quote",
        "create_payment_quote",
        "create_food_quote",
    }
)
ASKS = re.compile(r"\?|provide|need|share|send me|tell me", re.I)
KEY = "idempotency_key"
CONCURRENCY = 6


@dataclass(frozen=True)
class Case:
    """`tool` is the call that is right for the prompt and `args` what it must carry; with no `tool` the right
    answer is to ask, and any quote call is wrong. `args` values are compared after trimming to digits (for
    numbers) or lower case (for words). `then` is a second message, sent in the same chat once the first turn
    is over; the right answer to it is another quote of the same kind, so two cards."""

    prompt: str
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    then: str = ""


CASES = (
    Case("Buy ₦500 MTN airtime"),
    Case("Buy ₦1,000 MTN data"),
    Case("Send ₦5,000 to a friend"),
    Case("Order jollof rice for delivery", "search_menu", {"query": "jollof"}),
    Case(
        "Pay ₦2,500 to Ada Stores", "create_payment_quote", {"merchant": "ada stores", "amount_kobo": 250000}
    ),
    Case(
        "Buy 500 naira MTN airtime for 07031234567",
        "create_airtime_quote",
        {"network": "mtn", "phone": "07031234567", "amount_kobo": 50000},
    ),
    Case(
        "Buy ₦500 MTN airtime for 07031234567",
        "create_airtime_quote",
        {"network": "mtn", "phone": "07031234567", "amount_kobo": 50000},
        then="Buy the same again",
    ),
    Case(
        "Buy ₦1,000 MTN data for 07031234567",
        "create_data_quote",
        {"network": "mtn", "phone": "07031234567"},
    ),
    Case(
        "Send 5k to Ada Okafor, GTBank 0123456789",
        "create_transfer_quote",
        {"account_number": "0123456789", "bank": "GTBank", "amount_kobo": 500000},
    ),
)


def _same(want: Any, got: Any) -> bool:
    if isinstance(want, int):
        return got == want
    if str(want).isdigit():
        return re.sub(r"\D", "", str(got).replace("+234", "0")) == want
    return str(want).lower() in str(got).lower()


def _call_problems(call: dict[str, Any], case: Case) -> list[str]:
    """Why a quote call is wrong for this prompt: empty, not what the person said, or refused as invalid."""
    if case.tool != call["tool"]:
        given = {k: v for k, v in call["arguments"].items() if k not in (KEY, "amount_as_user_said")}
        return [f"{call['tool']} called with {json.dumps(given, ensure_ascii=False)}"]
    problems = [
        f"{name} is {call['arguments'].get(name)!r}"
        for name, want in case.args.items()
        if not _same(want, call["arguments"].get(name))
    ]
    if call["is_error"] and call["result"].startswith("Invalid arguments"):
        problems.append("the connector refused the arguments")
    return problems


def judge(case: Case, calls: list[dict[str, Any]], said: str) -> dict[str, Any]:
    quotes = [c for c in calls if c["tool"] in QUOTE_TOOLS]
    problems = [p for c in quotes for p in _call_problems(c, case)]
    asked = not quotes and bool(ASKS.search(said))
    made = sum(
        c["tool"] == case.tool
        and not c["is_error"]
        and not c["result"].startswith(REPEATED)
        and not _call_problems(c, case)
        for c in calls
    )
    return {
        "wrong": bool(problems),
        "problems": problems,
        "asked": asked,
        "right": made >= (2 if case.then else 1) if case.tool else asked and not problems,
    }


def _summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    results = {e["payload"]["call_id"]: e["payload"] for e in events if e["type"] == "tool"}
    calls = [
        {
            "tool": e["payload"]["tool"],
            "arguments": e["payload"]["arguments"],
            "is_error": e["payload"]["is_error"],
            "result": e["payload"]["result_text"][:160],
        }
        for e in events
        if e["type"] == "tool"
    ]
    assert len(results) == len(calls)
    replies = [e for e in events if e["type"] == "assistant"]
    return {
        "calls": calls,
        "said": " ".join(r["payload"]["text"] for r in replies).strip(),
        "notices": [e["payload"]["text"] for e in events if e["type"] == "notice"],
        "cards": sum(e["type"] == "card" for e in events),
        "repeats": sum(
            e["payload"]["result_text"].startswith(REPEATED) for e in events if e["type"] == "tool"
        ),
        "model_keys": sum(KEY in e["payload"]["arguments"] for e in events if e["type"] == "tool"),
        "finish_reasons": [r["payload"]["finish_reason"] for r in replies],
        "turn": events[-1]["payload"]["reason"],
    }


async def draw(case: Case, number: int, gate: asyncio.Semaphore) -> dict[str, Any]:
    async with gate, Visitor() as v:
        chat = await v.new_chat()
        sent = (await v.send(chat, case.prompt)).json()["seq"]
        try:
            events = await until(v.sse(chat), lambda e: finished(e) and e["seq"] > sent, timeout=240)
            if case.then:
                sent = (await v.send(chat, case.then)).json()["seq"]
                events = await until(v.sse(chat), lambda e: finished(e) and e["seq"] > sent, timeout=240)
        except TimeoutError:
            return {"prompt": case.prompt, "draw": number, "turn": "timeout", "calls": [], "said": ""}
    summary = _summary(events)
    return {
        "prompt": case.prompt,
        "draw": number,
        **summary,
        **judge(case, summary["calls"], summary["said"]),
        "cards_expected": (2 if case.then else 1) if case.tool else 0,
    }


def report(draws: list[dict[str, Any]], cases: list[Case]) -> None:
    print(
        f"{'prompt':<46}{'draws':>6}{'wrong':>7}{'asked':>7}{'right':>7}{'cards':>7}{'off':>5}{'repeats':>9}{'keys':>6}"
    )
    for case in cases:
        mine = [d for d in draws if d["prompt"] == case.prompt]
        asked = sum(d.get("asked", False) for d in mine)
        right = sum(d.get("right", False) for d in mine)
        cards = sum(d.get("cards", 0) for d in mine)
        off = sum(d.get("cards", 0) != d.get("cards_expected") for d in mine)
        repeats = sum(d.get("repeats", 0) for d in mine)
        model_keys = sum(d.get("model_keys", 0) for d in mine)
        wrong = sum(d.get("wrong", False) for d in mine)
        print(
            f"{case.prompt:<46}{len(mine):>6}{wrong:>7}{asked:>7}{right:>7}{cards:>7}{off:>5}{repeats:>9}{model_keys:>6}"
        )
    reasons = collections.Counter(r for d in draws for r in d.get("finish_reasons", []))
    print("finish_reason of every round:", dict(reasons))
    print("how the turns ended:", dict(collections.Counter(d["turn"] for d in draws)))
    print("cards: `off` counts draws whose number of cards is not what the prompt calls for (0 for an ask,")
    print(
        "1 otherwise); `repeats` are calls held back as a repeat of one in the same reply; `keys` are calls"
    )
    print("in which the model sent an idempotency key although it is not offered one.")
    for d in draws:
        if d.get("wrong"):
            print(f"  wrong: {d['prompt']!r} draw {d['draw']}: {'; '.join(d['problems'])}")
        elif not d.get("right") and not d.get("asked"):
            tools = [c["tool"] for c in d["calls"]]
            said, notices = d["said"][:100], d.get("notices")
            print(f"  other: {d['prompt']!r} draw {d['draw']}: {d['turn']}, {tools}, {said!r}, {notices}")


async def main(draws_per_prompt: int, only: str = "") -> None:
    gate = asyncio.Semaphore(CONCURRENCY)
    cases = [c for c in CASES if only.lower() in c.prompt.lower()]
    draws = await asyncio.gather(*[draw(case, n, gate) for case in cases for n in range(draws_per_prompt)])
    if path := os.environ.get("PROBE_LOG"):
        with open(path, "w") as out:
            out.writelines(json.dumps(d, ensure_ascii=False) + "\n" for d in draws)
    report(draws, cases)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5, sys.argv[2] if len(sys.argv) > 2 else ""))
