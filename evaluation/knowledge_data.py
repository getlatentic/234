# SPDX-License-Identifier: AGPL-3.0-or-later
"""The knowledge evaluation's data: the invented corpus in knowledge/eval, its questions, the gold passages
derived from the corpus by code, and the cases the model-level run is made of."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from checkout.knowledge.normalise import fold
from tools.knowledge_corpus import Source, load_all, rows_of

from .cases import Case, Turn

EVAL_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "eval"
KINDS = ("answer", "abstain", "injection")
LANGUAGES = ("en", "pcm", "yo", "ha", "ig")


class DataError(ValueError):
    pass


@dataclass(frozen=True)
class Question:
    id: str
    kind: str
    lang: str
    q: str
    source: str | None
    answer: str | None
    native_reviewed: bool
    split: str = "dev"
    split: str = "dev"
    forbidden: tuple[str, ...] = ()


def corpus(folder: Path = EVAL_DIR) -> dict[str, Source]:
    sources = load_all(folder)
    if problems := [f"{s.path.name}: {p}" for s in sources for p in s.problems]:
        raise DataError("; ".join(problems))
    return {s.id: s for s in sources}


def questions(folder: Path = EVAL_DIR) -> list[Question]:
    known = corpus(folder)
    rows = [
        json.loads(line) for line in (folder / "questions.jsonl").read_text().splitlines() if line.strip()
    ]
    made = [Question(**{**r, "forbidden": tuple(r.get("forbidden", ()))}) for r in rows]
    for q in made:
        if q.kind not in KINDS or q.lang not in LANGUAGES:
            raise DataError(f"{q.id}: kind {q.kind!r} or language {q.lang!r}")
        if (q.kind == "abstain") != (q.source is None):
            raise DataError(f"{q.id}: an abstain question has no source and any other has one")
        if q.source is not None and q.source not in known:
            raise DataError(f"{q.id}: no source {q.source}")
        if q.source and q.answer and not gold(q, known):
            raise DataError(f"{q.id}: no passage of {q.source} holds {q.answer!r}")
    if len({q.id for q in made}) != len(made):
        raise DataError("question ids are not unique")
    return made


def gold(question: Question, known: dict[str, Source]) -> list[str]:
    """The ids of the passages of the question's source that hold its answer: derived from the corpus, so a
    change to the chunker or a source moves the gold with it."""
    if question.source is None or question.answer is None:
        return []
    _, passages = rows_of(known[question.source])
    wanted = fold(question.answer.split("|")[0])
    return [p["id"] for p in passages if wanted in p["folded"]]


def outcome_of(question: Question, known: dict[str, Source]) -> dict[str, Any]:
    if question.kind == "abstain":
        return {"kind": "abstain"}
    base = {
        "source": question.source,
        "answer": question.answer,
        "link": known[question.source or ""].meta["url"],
    }
    if question.kind == "injection":
        return {"kind": "ignored", **base, "forbidden": list(question.forbidden)}
    return {"kind": "cited", **base}


def knowledge_cases(folder: Path = EVAL_DIR) -> list[Case]:
    known = corpus(folder)
    cases = []
    for q in questions(folder):
        outcome = outcome_of(q, known)
        injected = {"account_number": "0123456789"} if q.kind == "injection" else {}
        turn = Turn(q.q, (outcome,))
        cases.append(
            Case(
                q.id,
                "knowledge" if q.split == "dev" else "knowledge-held-out",
                q.kind,
                q.lang,
                (turn,),
                "reads the answer",
                injection=bool(injected),
                injected=injected,
            )
        )
    return cases
