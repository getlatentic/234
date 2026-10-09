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

    def clauses(self) -> tuple[str, tuple[Any, ...]]:
        pairs = (
            ("s.agency", self.agency),
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


class KnowledgeStore:
    def __init__(self, db: Db) -> None:
        self._db = db

    async def search(self, query: str, filters: Filters, limit: int = 5) -> list[dict[str, Any]]:
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
