# SPDX-License-Identifier: AGPL-3.0-or-later
"""Long chats with a real model, to see what compaction does to them: how many facts it keeps, what it adds
to a turn's latency, how large the requests stay, and whether the model still answers from what is left. A
script for the owner, not a test: it makes real model calls (about a thousand for five chats).

usage: tools/real-model.sh compaction [CHATS]         (the stack with the real model, then this)
       PORT_BASE=8940 VISITOR_CAP=5000 CONTEXT_WINDOW_TOKENS=12000 COMPACT_AT=0.6 KEEP_RECENT_TOKENS=2500 \\
         LLM_BASE_URL=... LLM_MODEL=openai.gpt-oss-120b LLM_API_KEY=... tools/real-model.sh compaction 5
PROBE_LOG=file.jsonl keeps every chat's numbers. A chat is 150 turns in English and Pidgin: small talk, things
the person says about themselves (a name to be called, an account number, a rent), airtime bought in quotes
that are paid, declined or left open. It is then asked five things about its past, and each answer is scored
without a model. The host lets a visitor send twelve messages a minute, so a chat takes about twelve minutes;
the chats run at once, each as a visitor of its own.
"""

import asyncio
import json
import os
import random
import re
import statistics
import sys
from dataclasses import dataclass, field
from typing import Any

from turns import messages
from turns.compaction import facts as fact_rules
from turns.eventlog import Event

from .long_chat import LongChat
from .worker_client import HOST, Visitor

TURNS = int(os.environ.get("PROBE_TURNS", "150"))
BUY_EVERY = 10
PHONES = ("07031234567", "08031234567", "09031234567")
NAME = "Oga Bukky"
ACCOUNT = "0123456789"
RENT = 45000
TALK = (
    "How far? Abeg remind me wetin you fit do for me",
    "Good morning, I hope the network dey work today",
    "Oga no wahala, I go check am later",
    "Thanks, that was quick. Abeg keep am short for me",
    "I dey fine, thank you. I dey on the bus and the signal no too strong",
    "Can you explain the steps again? I am not sure I followed",
    "One of my customers said she would settle tomorrow, I will remind her",
    "No problem at all, take your time",
    "Wetin be the cheapest thing you fit do for me this week?",
    "I sold twelve bags of rice today, business dey move small small",
    "My sister called me about the family meeting on Sunday, I must go",
    "The generator don spoil again, I no know wetin go happen for the shop",
    "Please just tell me if it is done when it is done",
    "I dey wait for the market women to come, them dey late today",
    "It rained all morning so nobody came to the shop early",
    "Abeg, no vex, I dey ask plenty questions today",
)
STATED = {
    7: f"Abeg always call me {NAME}, na so my people dey call me",
    23: f"My friend Ada Okafor banks with GTBank, her account number is {ACCOUNT}, I may send her something",
    61: "My shop rent is ₦45,000 every month and I pay it on the first",
    104: "I pay my shop assistant ₦18,500 every Friday",
}
QUESTIONS = (
    ("the last amount I paid", "What was the last amount I paid?"),
    ("Ada's account", "What is Ada's account number again?"),
    ("the name to use", "What name did I ask you to call me?"),
    (
        "the quote still open",
        "Which of my airtime quotes is still waiting for my approval? Give me its amount.",
    ),
    ("the rent", "How much is my shop rent?"),
)


@dataclass
class Buy:
    text: str
    kobo: int
    phone: str
    plan: str


def script(seed: int) -> list[str | Buy]:
    """The chat: each entry is a message, or a purchase that the person then pays for, declines or leaves."""
    rng = random.Random(seed)
    turns: list[str | Buy] = []
    bought = 0
    for n in range(TURNS):
        if n % BUY_EVERY == BUY_EVERY - 1:
            naira = 500 + 50 * bought + rng.randrange(0, 40) * 5
            phone = PHONES[(bought + seed) % len(PHONES)]
            plan = "open" if bought == TURNS // BUY_EVERY - 1 else ("pay", "decline", "pay")[bought % 3]
            ask = rng.choice(
                (f"Buy ₦{naira:,} MTN airtime for {phone}", f"abeg buy {naira} naira MTN airtime for {phone}")
            )
            turns.append(Buy(ask, naira * 100, phone, plan))
            bought += 1
        elif n in STATED:
            turns.append(STATED[n])
        else:
            turns.append(f"{rng.choice(TALK)}. ({n})")
    return turns


@dataclass
class Result:
    seed: int
    chat: str = ""
    compactions: list[dict[str, Any]] = field(default_factory=list)
    answers: list[dict[str, Any]] = field(default_factory=list)
    turn_seconds: list[float] = field(default_factory=list)
    compacting_turn_seconds: list[float] = field(default_factory=list)
    prompt_tokens: list[int] = field(default_factory=list)
    quotes_made: int = 0
    quotes_missed: list[str] = field(default_factory=list)
    retention: dict[str, Any] = field(default_factory=dict)
    error: str = ""


def _events(wire: list[dict[str, Any]]) -> list[Event]:
    return [Event(e["seq"], e["type"], e["task"], e["ref"], e["payload"], e["at"]) for e in wire]


async def _settle(chat: LongChat, buy: Buy, before: int) -> str:
    """What the person does with the card the purchase made; empty when it made none."""
    cards = chat.cards()
    if len(cards) <= before:
        return "no quote"
    card = cards[-1]
    if buy.plan == "pay":
        await chat.pay(card)
    elif buy.plan == "decline":
        await chat.decline(card)
    return buy.plan


def _paid_amounts(text: str) -> set[int]:
    return fact_rules.facts_in_text(text).amounts


def _plain(text: str) -> str:
    """The model's spaces include no-break and zero-width ones; a person reads them as plain ones or none."""
    return re.sub(r"[\u00a0\u202f\u2009]", " ", re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text))


def _score(question: str, expected: dict[str, Any], reply: str) -> bool:
    answer = _plain(reply)
    lowered = answer.lower()
    if question == "the name to use":
        return NAME.lower() in lowered
    if question == "Ada's account":
        return ACCOUNT in re.sub(r"[\s-]", "", answer)
    if question == "the rent":
        return "45,000" in answer or "45000" in answer or "45 000" in answer
    mentioned = _paid_amounts(answer)
    wanted = expected["kobo"]
    return wanted in mentioned and not (mentioned & expected["others"])


def _expected(plan: list[str | Buy], states: list[str]) -> dict[str, dict[str, Any]]:
    quotes = [(b, s) for b, s in zip([t for t in plan if isinstance(t, Buy)], states, strict=False)]
    made = [(b, s) for b, s in quotes if s != "no quote"]
    every = {b.kobo for b, _ in made}
    last_paid = next((b for b, s in reversed(made) if s == "pay"), None)
    open_one = next((b for b, s in reversed(made) if s == "open"), None)
    return {
        "the last amount I paid": {
            "kobo": last_paid.kobo if last_paid else 0,
            "others": every - {last_paid.kobo if last_paid else 0},
        },
        "the quote still open": {
            "kobo": open_one.kobo if open_one else 0,
            "others": every - {open_one.kobo if open_one else 0},
        },
        "Ada's account": {},
        "the name to use": {},
        "the rent": {},
    }


def _retention(events: list[Event]) -> dict[str, Any]:
    """How much of what the person said and was quoted is in front of the model at the end, and how much of it
    each compaction's summary kept by the model's own words (before a facts block, if one was added)."""
    needed = fact_rules.facts_of_events(events)
    context = "\n".join(
        m["content"] or "" for m in messages.render(events, "") if isinstance(m.get("content"), str)
    )
    lost = fact_rules.missing_from(context, needed, fact_rules.Facts())
    total = len(needed.amounts) + len(needed.phones) + len(needed.accounts)
    gone = len(lost.amounts) + len(lost.phones) + len(lost.accounts)
    per_summary = []
    for event in events:
        if event.type != "compaction" or event.payload["trigger"] == "fallback":
            continue
        covered = [e for e in events if e.seq <= event.payload["covers"]["last"]]
        kept_after = fact_rules.facts_of_events(
            [e for e in events if e.seq > event.payload["covers"]["last"]]
        )
        wanted = fact_rules.facts_of_events(covered)
        model_words = fact_rules.without_block(event.payload["summary"])
        missed = fact_rules.missing_from(model_words, wanted, kept_after)
        count = len(wanted.amounts) + len(wanted.phones) + len(wanted.accounts)
        per_summary.append(
            {
                "facts": count,
                "kept_by_the_model": count
                - (len(missed.amounts) + len(missed.phones) + len(missed.accounts)),
            }
        )
    return {"facts": total, "in_the_final_context": total - gone, "per_summary": per_summary}


async def run_probe(seed: int) -> Result:
    result = Result(seed)
    plan = script(seed)
    states: list[str] = []
    try:
        async with Visitor(HOST) as v, LongChat.open(v) as chat:
            result.chat = chat.chat
            for step in plan:
                before = len(chat.cards())
                if isinstance(step, Buy):
                    await chat.say(step.text)
                    states.append(await _settle(chat, step, before))
                else:
                    await chat.say(step)
            expected = _expected(plan, states)
            for question, text in QUESTIONS:
                events = await chat.say(text)
                reply = next(e for e in reversed(events) if e["type"] == "assistant")["payload"]["text"]
                result.answers.append(
                    {
                        "question": question,
                        "reply": reply,
                        "right": _score(question, expected[question], reply),
                    }
                )
            log = await v.log(chat.chat)
    except Exception as failure:
        result.error = f"{type(failure).__name__}: {failure}"
        return result
    events = _events(log)
    result.compactions = [e.payload | {"seq": e.seq} for e in events if e.type == "compaction"]
    result.quotes_made = sum(e.type == "card" for e in events)
    result.quotes_missed = [s for s in states if s == "no quote"]
    result.prompt_tokens = [
        e.payload["usage"]["prompt_tokens"]
        for e in events
        if e.type == "assistant" and e.payload.get("usage")
    ]
    result.turn_seconds, result.compacting_turn_seconds = _turn_times(events)
    result.retention = _retention(events)
    return result


def _turn_times(events: list[Event]) -> tuple[list[float], list[float]]:
    """Seconds from a turn's start to its end: the turns that did not compact, and those that did."""
    compacted = [e.seq for e in events if e.type == "compaction"]
    started = {e.task: e for e in events if e.type == "turn.started"}
    plain: list[float] = []
    with_compaction: list[float] = []
    for end in (e for e in events if e.type == "turn.finished" and e.task in started):
        begin = started[end.task]
        took = (end.at - begin.at) / 1000
        (with_compaction if any(begin.seq < seq < end.seq for seq in compacted) else plain).append(took)
    return plain, with_compaction


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))] if ordered else 0.0


def _facts_in(kept: list[dict[str, int]]) -> str:
    total, got = sum(k["facts"] for k in kept), sum(k["kept_by_the_model"] for k in kept)
    return f"{got}/{total}"


def report_compactions(r: Result) -> None:
    auto = [c for c in r.compactions if c["trigger"] == "auto"]
    how = {k: sum(c["verified"] == k for c in auto) for k in ("model", "retried", "block")}
    print(
        f"  compactions {len(r.compactions)} (auto {len(auto)}, fallback {len(r.compactions) - len(auto)}); "
        f"complete on the first try {how['model']}, after asking again {how['retried']}, "
        f"completed by rule {how['block']}"
    )
    if not auto:
        return
    seconds = [c["ms"] / 1000 for c in auto]
    before = _median([c["tokens"]["before"] for c in auto])
    after = _median([c["tokens"]["after"] for c in auto])
    size = _median([len(c["summary"]) / 4 for c in auto])
    print(
        f"  a compaction takes median {_median(seconds):.1f} s, max {max(seconds):.1f} s; "
        f"context {before:.0f} -> {after:.0f} tokens; summary {size:.0f} tokens"
    )


def report_turns(r: Result) -> None:
    plain, compacting = r.turn_seconds, r.compacting_turn_seconds
    print(
        f"  turns without a compaction {len(plain)}: median {_median(plain):.1f} s, "
        f"p95 {_percentile(plain, 0.95):.1f} s; with one {len(compacting)}: "
        f"median {_median(compacting):.1f} s, max {max(compacting, default=0):.1f} s "
        f"(added {_median(compacting) - _median(plain):.1f} s)"
    )
    print(
        f"  requests: max {max(r.prompt_tokens, default=0)} prompt tokens, "
        f"median {_median(r.prompt_tokens):.0f}"
    )
    print(
        f"  facts the model's own words kept in each summary: {_facts_in(r.retention['per_summary'])}; "
        f"in the final context: {r.retention['in_the_final_context']}/{r.retention['facts']}"
    )


def report_answers(r: Result) -> None:
    print(
        f"  quotes made {r.quotes_made}; purchases that made none {len(r.quotes_missed)}; "
        f"answers {sum(a['right'] for a in r.answers)}/{len(r.answers)} right"
    )
    for answer in r.answers:
        print(
            f"    {'ok   ' if answer['right'] else 'WRONG'} {answer['question']}: {answer['reply'][:140]!r}"
        )


def report(results: list[Result]) -> None:
    for r in results:
        print(f"\nchat {r.seed} ({r.chat})" + (f"  FAILED: {r.error}" if r.error else ""))
        if not r.error:
            report_compactions(r)
            report_turns(r)
            report_answers(r)
    done = [r for r in results if not r.error]
    right = sum(a["right"] for r in done for a in r.answers)
    asked = sum(len(r.answers) for r in done)
    print(f"\n{len(done)} of {len(results)} chats finished; {right} of {asked} answers right")


async def main(chats: int) -> None:
    results = await asyncio.gather(*(run_probe(seed) for seed in range(1, chats + 1)))
    report(results)
    if log := os.environ.get("PROBE_LOG"):
        with open(log, "w") as out:
            for r in results:
                out.write(json.dumps(r.__dict__, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5))
