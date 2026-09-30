# SPDX-License-Identifier: AGPL-3.0-or-later
"""The cases: loaded from `cases.jsonl` and checked for shape, so a typo fails a test, not a run."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CASES_FILE = Path(__file__).with_name("cases.jsonl")
SPLITS = ("dev", "held-out", "tuning")
OUTCOME_KINDS = {
    "quote": {"tool", "args"},
    "ask": {"mention"},
    "decline": set(),
    "menu": set(),
    "refused": {"tool", "args", "code"},
    "no_approve": set(),
}
MAX_MESSAGE = 500


class CaseError(ValueError):
    pass


@dataclass(frozen=True)
class Turn:
    """`said` holds the values the message itself contains (a field the person gave, whatever the outcome),
    so a call that uses them is not counted as inventing them."""

    say: str
    expect: tuple[dict[str, Any], ...]
    said: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Case:
    id: str
    split: str
    category: str
    lang: str
    turns: tuple[Turn, ...]
    user_next: str
    approved_kobo: tuple[int, ...] = ()
    injection: bool = False
    injected: dict[str, Any] = field(default_factory=dict)


def _outcome(case_id: str, outcome: dict[str, Any]) -> dict[str, Any]:
    kind = outcome.get("kind")
    if kind not in OUTCOME_KINDS:
        raise CaseError(f"{case_id}: unknown outcome kind {kind!r}")
    if set(outcome) - {"kind"} != OUTCOME_KINDS[kind]:
        raise CaseError(f"{case_id}: a {kind} outcome has the keys {sorted(OUTCOME_KINDS[kind])}")
    return outcome


def _case(raw: dict[str, Any]) -> Case:
    case_id = raw["id"]
    if raw["split"] not in SPLITS:
        raise CaseError(f"{case_id}: split {raw['split']!r}")
    turns = tuple(
        Turn(t["say"], tuple(_outcome(case_id, o) for o in t["expect"]), t.get("said", {}))
        for t in raw["turns"]
    )
    if not 1 <= len(turns) <= 2:
        raise CaseError(f"{case_id}: a case has one or two turns")
    if any(not t.expect or not t.say.strip() or len(t.say) > MAX_MESSAGE for t in turns):
        raise CaseError(
            f"{case_id}: every turn has a message of at most {MAX_MESSAGE} characters and an outcome"
        )
    if not raw.get("user_next", "").strip():
        raise CaseError(f"{case_id}: user_next is empty")
    return Case(
        case_id,
        raw["split"],
        raw["category"],
        raw["lang"],
        turns,
        raw["user_next"],
        tuple(raw.get("setup", {}).get("approved_kobo", ())),
        bool(raw.get("injection")),
        raw.get("injected", {}),
    )


def load_cases(path: Path = CASES_FILE) -> list[Case]:
    cases = [_case(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        raise CaseError("case ids are not unique")
    return cases
