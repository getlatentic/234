# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search over the passages (docs/knowledge.md). Every statement here reads only sources that are
'published': the status is a condition of the query, not an argument, so nothing a caller passes can reach a
draft or a retired source."""

import re
from dataclasses import dataclass
from typing import Any

from ..db import Db
from .normalise import fold

MAX_TERMS = 12
MAX_RESULTS = 8
_WORD = re.compile(r"[^\W_]+")
_STOP = frozenset(
    {"a", "an", "the", "of", "to", "for", "in", "on", "at", "is", "are", "do", "does", "how", "what", "which"}
    | {"who", "i", "my", "me", "we", "you", "your", "it", "and", "or", "can", "should", "would", "will"}
    | {"be", "get", "want", "need"}
)

_PASSAGE = (
    "SELECT p.id AS passage_id, p.ord, p.start_offset, p.end_offset, p.text, s.id AS source_id, s.title, "
    "s.url, s.agency, s.content_type, s.trust_tier, s.retrieved_at, s.published_at, s.language"
)
_PUBLISHED = "s.status = 'published'"


@dataclass(frozen=True)
class Filters:
    agency: str | None = None
    content_type: str | None = None
    trust_tier: int | None = None

    @property
    def any(self) -> bool:
        return any(v is not None for v in (self.agency, self.content_type, self.trust_tier))

    def clauses(self) -> tuple[str, tuple[Any, ...]]:
        pairs = (
            ("LOWER(s.agency)", self.agency.lower() if self.agency else None),
            ("s.content_type", self.content_type),
            ("s.trust_tier", self.trust_tier),
        )
        used = [(column, value) for column, value in pairs if value is not None]
        return "".join(f" AND {column} = ?" for column, _ in used), tuple(v for _, v in used)


def match_terms(query: str) -> str:
    """The words of a question as an FTS5 expression: folded, the small words dropped, each one quoted so
    nothing a person types is read as syntax, and joined by OR so BM25 ranks what matches most."""
    words = [w for w in _WORD.findall(fold(query)) if w not in _STOP]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words[:MAX_TERMS]))


def _ids(rows: list[dict[str, Any]]) -> set[str]:
    return {r["passage_id"] for r in rows}


class KnowledgeStore:
    def __init__(self, db: Db) -> None:
        self._db = db

    async def search(self, query: str, filters: Filters, limit: int = 5) -> tuple[list[dict[str, Any]], bool]:
        """The best passages, those that match the filters first, and whether some do not. A filter is the
        model's guess at where the answer is (it names an agency from memory): it puts passages first but does
        not keep the others out, so a wrong guess does not hide the right passage or read as "the sources say
        nothing"."""
        found = await self._ranked(query, filters, limit)
        if not filters.any:
            return found, False
        wider = [r for r in await self._ranked(query, Filters(), limit) if r["passage_id"] not in _ids(found)]
        return [*found, *wider][:limit], bool(wider) and len(found) < limit

    async def _ranked(self, query: str, filters: Filters, limit: int) -> list[dict[str, Any]]:
        terms = match_terms(query)
        if not terms:
            return []
        clause, params = filters.clauses()
        return await self._db.rows(
            f"{_PASSAGE}, bm25(knowledge_fts) AS rank FROM knowledge_fts "
            "JOIN knowledge_passage p ON p.seq = knowledge_fts.rowid "
            "JOIN knowledge_source s ON s.id = p.source_id "
            f"WHERE knowledge_fts MATCH ? AND {_PUBLISHED}{clause} "
            "ORDER BY rank, p.id LIMIT ?",
            terms,
            *params,
            min(max(limit, 1), MAX_RESULTS),
        )

    async def open_passage(self, passage_id: str, around: int = 1) -> list[dict[str, Any]]:
        """The passage and `around` passages either side of it in its source, in order."""
        return await self._db.rows(
            f"{_PASSAGE} FROM knowledge_passage p JOIN knowledge_source s ON s.id = p.source_id "
            "JOIN knowledge_passage focus ON focus.source_id = p.source_id AND focus.id = ? "
            f"WHERE {_PUBLISHED} AND p.ord BETWEEN focus.ord - ? AND focus.ord + ? ORDER BY p.ord",
            passage_id,
            around,
            around,
        )

    async def sources(self, agency: str | None = None) -> list[dict[str, Any]]:
        clause, params = Filters(agency=agency).clauses()
        return await self._db.rows(
            "SELECT s.id, s.agency, s.title, s.url, s.content_type, s.trust_tier, s.language, "
            "s.retrieved_at, (SELECT COUNT(*) FROM knowledge_passage p WHERE p.source_id = s.id) AS passages "
            f"FROM knowledge_source s WHERE {_PUBLISHED}{clause} ORDER BY s.agency, s.title",
            *params,
        )
