# SPDX-License-Identifier: AGPL-3.0-or-later
"""Re-scores a results file offline and prints the tables RESULTS.md quotes.

    cd host && PYTHONPATH=..:../checkout/src uv run python -m evaluation.report \\
        ../evaluation/results/FILE.jsonl [--show ID]

The stored turn records are scored again with the current `score.py`, so a fix to the scorer applies to
a run already made, and the same file always gives the same tables.
"""

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .cases import Case, load_cases
from .score import CaseScore, score_case
from .stats import cases_passing_every_draw, group_rates, latency_summary, rate, tally

KINDS = (
    "wrong_amount",
    "wrong_recipient",
    "wrong_number",
    "wrong_product",
    "approve",
    "false_claim",
    "injection",
)


def load_draws(path: Path, cases: dict[str, Case]) -> list[dict[str, Any]]:
    draws = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for draw in draws:
        draw["scored"] = score_case(cases[draw["case"]], draw["turns"])
    return draws


def passed(draw: dict[str, Any]) -> bool:
    return draw["scored"].ok


def table(title: str, rows: dict[str, tuple[int, int]], total: tuple[int, int]) -> list[str]:
    lines = [f"| {title} | draws passed (95% Wilson) |", "|---|---|"]
    lines += [f"| {name} | {rate(*counts)} |" for name, counts in rows.items()]
    return [*lines, f"| **all** | **{rate(*total)}** |"]


def dangerous_table(draws: list[dict[str, Any]]) -> list[str]:
    lines = ["| Dangerous failure | draws | a card reached the person |", "|---|---|---|"]
    for kind in KINDS:
        hits = [d for d in draws if any(f.kind == kind for f in d["scored"].findings)]
        cards = [d for d in hits if any(f.kind == kind and f.card for f in d["scored"].findings)]
        lines.append(f"| {kind} | {len(hits)} | {len(cards)} |")
    return lines


def outcome_text(outcome: dict[str, Any]) -> str:
    args = json.dumps(outcome["args"], ensure_ascii=False) if "args" in outcome else ""
    return " ".join(
        part for part in (outcome["kind"], outcome.get("tool", ""), args, outcome.get("code", "")) if part
    )


def call_text(call: dict[str, Any]) -> str:
    shown = {k: v for k, v in call["arguments"].items() if k != "amount_as_user_said"}
    return f"{call['tool']}({json.dumps(shown, ensure_ascii=False)}){' refused' if call['is_error'] else ''}"


def happened(record: dict[str, Any] | None) -> str:
    if record is None:
        return "the run ended before this turn"
    calls = "; ".join(call_text(c) for c in record["calls"]) or "no call"
    return f"{calls}; {len(record['cards'])} card(s); end {record['end']}; said {record['reply'][:110]!r}"


def why(turn: Any) -> str:
    if turn is None:
        return "no record"
    if turn.invariants:
        return "; ".join(turn.invariants)
    return " / ".join(p[0] for p in turn.problems if p)


def first_failed_turn(scored: CaseScore, case: Case) -> int:
    return next(
        (i for i, t in enumerate(scored.turns) if not t.ok), min(len(scored.turns), len(case.turns) - 1)
    )


def failures(draws: list[dict[str, Any]], cases: dict[str, Case]) -> list[str]:
    lines = ["| case | draw | expected | what happened | why |", "|---|---|---|---|---|"]
    for d in (d for d in draws if not passed(d)):
        case, scored = cases[d["case"]], d["scored"]
        i = first_failed_turn(scored, case)
        expected = " OR ".join(outcome_text(o) for o in case.turns[i].expect)
        record = d["turns"][i] if i < len(d["turns"]) else None
        turn = scored.turns[i] if i < len(scored.turns) else None
        lines.append(f"| {d['case']} | {d['draw']} | {expected} | {happened(record)} | {why(turn)} |")
    return lines


def rounds_summary(draws: list[dict[str, Any]]) -> list[str]:
    turns = [t for d in draws for t in d["turns"]]
    seconds = [t["latency_ms"] / 1000 for t in turns if t["latency_ms"] is not None]
    return [
        f"finish_reason of every round: {tally(r for t in turns for r in t['finish_reasons'])}",
        f"how the turns ended: {tally(t['end'] for t in turns)}",
        f"latency: {latency_summary(seconds)}",
    ]


def refusals(draws: list[dict[str, Any]]) -> str:
    """Every call the connector or the host refused, by the start of its answer."""
    calls = [c for d in draws for t in d["turns"] for c in t["calls"] if c["is_error"]]
    return f"calls refused: {tally(c['result'].split(':')[0][:40] for c in calls)}"


def restated(draws: list[dict[str, Any]]) -> str:
    changed = [f"{d['case']}#{d['draw']}" for d in draws if d["score"]["ok"] != passed(d)]
    return f"verdicts that differ from the ones stored when the run was made: {changed or 'none'}"


def by(draws: list[dict[str, Any]], key: Callable[[dict[str, Any]], str]) -> dict[str, tuple[int, int]]:
    return group_rates(draws, key, passed)


def transcript(draw: dict[str, Any]) -> list[str]:
    head = f"--- {draw['case']} draw {draw['draw']}: {'pass' if passed(draw) else 'FAIL'}"
    return [head, *(json.dumps(t["log"], ensure_ascii=False, indent=1) for t in draw["turns"])]


def report(draws: list[dict[str, Any]], cases: dict[str, Case], show: list[str]) -> list[str]:
    total = (sum(map(passed, draws)), len(draws))
    every = cases_passing_every_draw(draws, passed)
    broken = sum(d["scored"].infra or bool(d["error"]) for d in draws)
    out = [f"{len(draws)} draws of {every[1]} cases", ""]
    out += [*table("category", by(draws, lambda d: d["category"]), total), ""]
    out += [*table("language", by(draws, lambda d: d["lang"]), total), ""]
    out += [f"cases that passed every draw: {every[0]}/{every[1]}", ""]
    out += [*dangerous_table(draws), ""]
    out += [f"infrastructure failures (no answer, error notice, setup): {broken}", *rounds_summary(draws)]
    out += [refusals(draws), restated(draws), ""]
    out += failures(draws, cases)
    for draw in (d for d in draws if d["case"] in show):
        out += ["", *transcript(draw)]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("results", type=Path)
    parser.add_argument("--show", nargs="*", default=[], help="case ids whose transcripts are printed")
    args = parser.parse_args()
    cases = {c.id: c for c in load_cases()}
    print("\n".join(report(load_draws(args.results, cases), cases, args.show)))


if __name__ == "__main__":
    main()
