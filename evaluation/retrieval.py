# SPDX-License-Identifier: AGPL-3.0-or-later
"""Retrieval on its own, with no model: does the right passage come back in the first five for each question
(recall@5), overall and by language. The corpus is loaded into SQLite exactly as the connectors' database
holds it, and the gold passages are derived from the corpus (knowledge_data.py).

    PYTHONPATH=.:host/src:checkout/src:checkout uv run --project host python -m evaluation.retrieval

from the repository's root.
"""

import asyncio
import sys
from collections import defaultdict

from checkout.knowledge.store import Filters, KnowledgeStore
from checkout.sqlite_db import SqliteDb
from tools.knowledge_corpus import load_all
from tools.knowledge_load import statements

from . import gate
from .knowledge_data import EVAL_DIR, corpus, gold, questions


def loaded() -> SqliteDb:
    db = SqliteDb()
    db.connection.executescript("\n".join(statements(load_all(EVAL_DIR))))
    return db


async def recall(k: int = 5) -> tuple[float, dict[str, float], list[str]]:
    """Recall@k over the questions that have an answer, by language, and the questions that missed."""
    store, known = KnowledgeStore(loaded()), corpus()
    hits: dict[str, list[bool]] = defaultdict(list)
    missed = []
    for q in (q for q in questions() if q.kind != "abstain"):
        found = await store.search(q.q, Filters(), k)
        ok = bool({p["passage_id"] for p in found} & set(gold(q, known)))
        hits[q.lang].append(ok)
        if not ok:
            missed.append(q.id)
    every = [ok for oks in hits.values() for ok in oks]
    return (
        gate.rate(sum(every), len(every)),
        {lang: gate.rate(sum(o), len(o)) for lang, o in hits.items()},
        missed,
    )


def main() -> int:
    overall, per_language, missed = asyncio.run(recall())
    print(
        f"recall@5 {overall:.2f}  " + "  ".join(f"{lang} {v:.2f}" for lang, v in sorted(per_language.items()))
    )
    if missed:
        print("missed:", ", ".join(missed))
    problems = gate.retrieval_problems(overall, per_language)
    print("\n".join(problems) or "The retrieval gate is met.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
