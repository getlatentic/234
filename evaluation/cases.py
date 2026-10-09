# SPDX-License-Identifier: AGPL-3.0-or-later
"""The cases: loaded from `cases.jsonl` and checked for shape, so a typo fails a test, not a run."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CASES_FILE = Path(__file__).with_name("cases.jsonl")
SPLITS = ("dev", "held-out", "tuning", "memory", "talk", "knowledge", "knowledge-held-out")
OUTCOME_KINDS = {
    "quote": {"tool", "args"},
    "ask": {"mention"},
    "decline": set(),
    "menu": set(),
    "refused": {"tool", "args", "code"},
    "no_approve": set(),
    "remember": {"note_kind", "args", "contains"},
    "update": {"id", "contains"},
    "forget": {"ids"},
    "answer": {"mention"},
    "not_saved": set(),
    "no_memory": set(),
    "talk": {"mention", "not_mention"},
    "cited": {"source", "answer", "link"},
    "abstain": set(),
    "ignored": {"source", "answer", "link", "forbidden"},
}
NOTE_KEYS = {
    "recipient": {"ref", "kind", "title", "account_number", "bank"},
    "preference": {"ref", "kind", "title", "hook", "body"},
    "fact": {"ref", "kind", "title", "hook", "body"},
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
    via: str = "send"


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
    account: bool = False
    """The person is signed in: the draw is made as an account, which has memory."""
    notes: tuple[dict[str, Any], ...] = ()
    """What the account has saved before the first turn, each with a `ref` that an outcome names as `@ref`."""


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
        Turn(
            t["say"],
            tuple(_outcome(case_id, o) for o in t["expect"]),
            t.get("said", {}),
            t.get("via", "send"),
        )
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
    notes = tuple(_note(case_id, n) for n in raw.get("setup", {}).get("notes", ()))
    account = bool(raw.get("account"))
    if notes and not account:
        raise CaseError(f"{case_id}: notes are the account's: the case needs account true")
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
        account,
        notes,
    )


def _note(case_id: str, note: dict[str, Any]) -> dict[str, Any]:
    wanted = NOTE_KEYS.get(note.get("kind", ""))
    if wanted is None or set(note) != wanted:
        raise CaseError(f"{case_id}: a note of kind {note.get('kind')!r} has the keys {sorted(wanted or ())}")
    return note


def load_cases(path: Path = CASES_FILE) -> list[Case]:
    cases = [_case(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        raise CaseError("case ids are not unique")
    return cases
