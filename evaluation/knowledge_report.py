# SPDX-License-Identifier: AGPL-3.0-or-later
"""Re-scores a results file of the knowledge splits offline and prints what RESULTS.md quotes: by kind of
outcome, the draws that were right, that showed the source's link, that stated something no source gave, that
showed a source line no page proves, and the failures.

    cd host && PYTHONPATH=src:..:../checkout/src:../checkout uv run python -m evaluation.knowledge_report \\
        ../evaluation/results/FILE.jsonl [--only before,after]

The stored turn records are scored again with the current `knowledge_score.py`, so the same file always gives
the same table, and two files (before and after a change) are compared on the same scorer.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import knowledge_score
from .knowledge_data import knowledge_cases

COLUMNS = ("ok", "cited", "wrong", "unproven", "abstained", "obeyed")


def scored(path: Path) -> list[dict[str, Any]]:
    outcomes = {c.id: c.turns[0].expect[0] for c in knowledge_cases()}
    draws = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [
        {
            "case": d["case"],
            "draw": d["draw"],
            "kind": outcomes[d["case"]]["kind"],
            "turn": d["turns"][0],
            "problems": knowledge_score.CHECKS[outcomes[d["case"]]["kind"]](
                outcomes[d["case"]], d["turns"][0]
            ),
            **knowledge_score.flags(outcomes[d["case"]], d["turns"][0]),
        }
        for d in draws
    ]


def table(draws: list[dict[str, Any]]) -> list[str]:
    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in draws:
        by_kind[d["kind"]].append(d)
    lines = ["| kind | draws | " + " | ".join(COLUMNS) + " |", "|---|---|" + "---|" * len(COLUMNS)]
    for kind, group in sorted(by_kind.items()):
        lines.append(
            f"| {kind} | {len(group)} | " + " | ".join(str(sum(d[c] for d in group)) for c in COLUMNS) + " |"
        )
    total = " | ".join(str(sum(d[c] for d in draws)) for c in COLUMNS)
    return [*lines, f"| **all** | **{len(draws)}** | {total} |"]


def failures(draws: list[dict[str, Any]]) -> list[str]:
    lines = []
    for d in draws:
        if not d["ok"] or d["unproven"]:
            shown = [n for n in d["turn"]["notices"] if n.startswith("Source:")]
            lines.append(f"{d['case']}#{d['draw']} {d['kind']} ok={d['ok']} unproven={d['unproven']}")
            lines.append(f"    reply: {d['turn']['reply'][:200]!r}")
            lines.append(f"    lines: {shown}")
            lines.append(f"    problems: {d['problems']}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("results", type=Path)
    parser.add_argument("--only", default="", help="comma-separated case ids")
    args = parser.parse_args()
    draws = [d for d in scored(args.results) if not args.only or d["case"] in args.only.split(",")]
    print("\n".join([*table(draws), "", *failures(draws)]))


if __name__ == "__main__":
    main()
