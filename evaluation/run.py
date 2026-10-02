# SPDX-License-Identifier: AGPL-3.0-or-later
"""Runs the cases against the local stack with the real model, one fresh visitor and chat per draw, and writes
one line per draw to the results file: the turn records (every call with its arguments and result, the
cards, the replies, every round's finish_reason, how the turn ended) and their score.

Start the stack first (`tools/real-model.sh`), then, from `host/`:

    PORT_BASE=8920 PYTHONPATH=src:..:../checkout/src uv run python -u -m evaluation.run \\
        --split held-out --draws 3 --out ../evaluation/results/held-out.jsonl

The memory split signs people in: start that stack with `AUTH=1 VISITOR_CAP=0 tools/real-model.sh` and
run with `--split memory`.

The model's answers are never judged by another model; `score.py` compares them with the case. A draw is a
new visitor, so its ledger owner is new, its daily allowance is new, and a case's limits are its own.
"""

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from tests.worker_client import Visitor, finished, until

from turns.prompt import system_prompt
from turns.settings import Settings

from .cases import Case, load_cases
from .redo import plan
from .score import score_case
from .signed_in import Accounts, SetupFailed, live_notes, set_up_notes
from .transcript import turns_of

TURN_TIMEOUT = 240
DAILY_LIMIT_KOBO = 10_000_000
PROTOCOL = "2025-11-25"
ROOT = Path(__file__).resolve().parent.parent


async def mcp(
    http: httpx.AsyncClient, url: str, owner: str, tool: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """One tool call to a connector as `owner`, the way the host makes it, with no model in between."""
    headers = {
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": PROTOCOL,
        "x-ledger-owner": owner,
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    answer = (await http.post(url, json=body, headers=headers)).json()
    result = answer.get("result")
    if result is None or result.get("isError"):
        raise SetupFailed(f"{tool}: {json.dumps(answer)[:200]}")
    return result


async def approve_spend(checkout: str, owner: str, amounts_kobo: tuple[int, ...]) -> None:
    """Uses up part of the owner's daily allowance: each amount is quoted and approved, as a card would."""
    url = f"{checkout}/paystack-pay/mcp"
    async with httpx.AsyncClient(timeout=30) as http:
        for kobo in amounts_kobo:
            made = await mcp(
                http,
                url,
                owner,
                "create_payment_quote",
                {
                    "amount_kobo": kobo,
                    "amount_as_user_said": str(kobo // 100),
                    "description": "Payment",
                    "merchant": "Setup",
                    "idempotency_key": secrets.token_hex(12),
                },
            )
            approve = {
                "quote_id": made["structuredContent"]["quote"]["id"],
                "approval_token": made["_meta"]["approvalToken"],
                "displayed_amount_kobo": kobo,
            }
            await mcp(http, url, owner, "approve_quote", approve)


def owner_of(visitor: Visitor) -> str:
    """The ledger owner of a visitor is the id inside the signed cookie."""
    return visitor.http.cookies.get("visitor", "").split(":")[0]


async def converse(visitor: Visitor, case: Case) -> list[dict[str, Any]]:
    chat = await visitor.new_chat()
    events: list[dict[str, Any]] = []
    try:
        for turn in case.turns:
            sent = await visitor.send(chat, turn.say, "message" if turn.via == "card" else "send")
            if sent.status_code != 200:
                raise SetupFailed(f"the message was refused: HTTP {sent.status_code} {sent.text[:100]}")
            seq = sent.json()["seq"]
            events = await until(
                visitor.sse(chat), lambda e, s=seq: finished(e) and e["seq"] > s, TURN_TIMEOUT
            )
    except TimeoutError:
        events = await visitor.log(chat)
    return events


async def play(
    case: Case, urls: dict[str, str], visitor: Visitor, owner: str | None
) -> tuple[list, dict, list]:
    """One draw's conversation: what the account had saved is set up, the daily allowance is used as the case
    says, the turns are sent, and what the account holds afterwards is read."""
    refs: dict[str, str] = {}
    if case.account and owner:
        refs = await set_up_notes(urls["checkout"], owner, case.notes)
    if case.approved_kobo:
        await approve_spend(urls["checkout"], owner or owner_of(visitor), case.approved_kobo)
    events = await converse(visitor, case)
    live = await live_notes(urls["checkout"], owner) if case.account and owner else []
    return events, refs, live


async def draw(
    case: Case, number: int, urls: dict[str, str], gate: asyncio.Semaphore, accounts: Accounts | None = None
) -> dict[str, Any]:
    started, error = time.monotonic(), None
    events: list[dict[str, Any]] = []
    refs: dict[str, str] = {}
    live: list[str] = []
    async with gate:
        try:
            if case.account:
                if accounts is None:
                    raise SetupFailed("a signed-in case needs the stack started with AUTH=1")
                async with accounts.lease() as (visitor, owner):
                    events, refs, live = await play(case, urls, visitor, owner)
            else:
                async with Visitor(urls["host"]) as visitor:
                    events, refs, live = await play(case, urls, visitor, None)
        except (SetupFailed, httpx.HTTPError) as failure:
            error = f"{type(failure).__name__}: {failure}"
    turns = turns_of(events)
    return {
        "case": case.id,
        "split": case.split,
        "category": case.category,
        "lang": case.lang,
        "draw": number,
        "error": error,
        "seconds": round(time.monotonic() - started, 1),
        "refs": refs,
        "live_ids": live,
        "turns": turns,
        "score": score_case(case, turns, refs, live).as_dict(),
    }


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def metadata(args: argparse.Namespace, cases: list[Case]) -> dict[str, Any]:
    settings = Settings.from_env(os.environ.get)
    prompt = system_prompt(settings.connectors)
    memory_prompt = system_prompt(settings.connectors, memory=True)
    return {
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "split": args.split,
        "draws_per_case": args.draws,
        "cases": len(cases),
        "model": settings.llm_model,
        "endpoint_host": urlsplit(settings.llm_base_url).netloc,
        "reasoning_effort": settings.reasoning_effort,
        "tool_choice": "auto",
        "temperature": "not sent: the endpoint's default",
        "connectors": list(settings.connectors),
        "repo_head": git("rev-parse", "HEAD"),
        "prompt_commit": git("log", "-1", "--format=%H", "--", "host/src/turns/prompt.py"),
        "tree_clean": not git("status", "--porcelain", "--", "host", "checkout"),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt": prompt,
        "prompt_with_memory_sha256": hashlib.sha256(memory_prompt.encode()).hexdigest(),
        "prompt_with_memory": memory_prompt,
    }


def pick(cases: list[Case], args: argparse.Namespace) -> list[Case]:
    chosen = [c for c in cases if args.split == "all" or c.split == args.split]
    if args.only:
        wanted = set(args.only.split(","))
        chosen = [c for c in chosen if c.id in wanted or c.category in wanted]
    return chosen


async def run(args: argparse.Namespace) -> None:
    base = int(os.environ.get("PORT_BASE", "8900"))
    urls = {"checkout": f"http://localhost:{base}", "host": f"http://localhost:{base + 1}"}
    cases = pick(load_cases(), args)
    draws, kept = plan(cases, args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = metadata(args, cases) | (
        {"redo_of": Path(args.redo).name, "redone": [f"{c.id}#{n}" for c, n in draws]} if args.redo else {}
    )
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    async with httpx.AsyncClient() as http:
        await http.post(f"{urls['checkout']}/test/reset")
        daily = (await http.get(f"{urls['checkout']}/test/summary")).json()["dailyLimitKobo"]
    if daily != DAILY_LIMIT_KOBO:
        sys.exit(f"The cases assume a daily limit of {DAILY_LIMIT_KOBO} kobo; the connectors have {daily}.")
    gate, write = asyncio.Semaphore(args.concurrency), asyncio.Lock()
    passed = failed = 0
    accounts = None
    if any(case.account for case in cases):
        accounts = Accounts(urls["host"], f"127.0.0.1:{base + 7}", args.concurrency)
        await accounts.start()

    async def one(case: Case, number: int, sink) -> None:
        nonlocal passed, failed
        result = await draw(case, number, urls, gate, accounts)
        ok = result["score"]["ok"]
        passed, failed = passed + ok, failed + (not ok)
        async with write:
            sink.write(json.dumps(result, ensure_ascii=False) + "\n")
            sink.flush()
        verdict = "pass" if ok else "FAIL"
        print(
            f"{verdict} {case.id} draw {number} ({result['seconds']} s) [{passed} pass, {failed} fail]",
            flush=True,
        )

    try:
        with out.open("w") as sink:
            sink.writelines(json.dumps(d, ensure_ascii=False) + "\n" for d in kept)
            await asyncio.gather(*[one(c, n, sink) for c, n in draws])
    finally:
        if accounts is not None:
            await accounts.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--split", choices=["dev", "held-out", "tuning", "memory", "all"], default="held-out")
    parser.add_argument("--draws", type=int, default=3)
    parser.add_argument("--only", default="", help="comma-separated case ids or categories")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--redo",
        default="",
        help="an earlier results file: keep every draw that answered and draw again only those lost to "
        "infrastructure (an error, or a turn that did not end), never a wrong answer",
    )
    args = parser.parse_args()
    if not args.out.endswith(".jsonl"):
        sys.exit("--out is a .jsonl file")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
