# SPDX-License-Identifier: AGPL-3.0-or-later
"""Checks the corpus and turns it into SQL for the connectors' database.

PYTHONPATH=src uv run python -m tools.knowledge_load check   exits 1 with the problems, 0 when sound
PYTHONPATH=src uv run python -m tools.knowledge_load sql     replaces what the database holds
PYTHONPATH=src uv run python -m tools.knowledge_load report  stale, unreviewed and retired sources

`--dir FOLDER` reads another folder than knowledge/sources (the local stack loads knowledge/fixtures).
"""

import sys
from pathlib import Path
from typing import Any

from tools.knowledge_corpus import SOURCES, Source, is_stale, load_all, rows_of

SOURCE_COLUMNS = (
    "id", "agency", "title", "url", "content_type", "language", "trust_tier", "status",
    "retrieved_at", "published_at", "reviewed_by", "reviewed_at", "checksum",
)  # fmt: skip
PASSAGE_COLUMNS = ("id", "source_id", "ord", "start_offset", "end_offset", "text", "folded")


def literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def insert(table: str, columns: tuple[str, ...], values: dict[str, Any]) -> str:
    names, literals = ", ".join(columns), ", ".join(literal(values[c]) for c in columns)
    return f"INSERT INTO {table} ({names}) VALUES ({literals});"


def statements(sources: list[Source]) -> list[str]:
    ids = ", ".join(literal(s.id) for s in sources) or "''"
    out = [f"DELETE FROM knowledge_source WHERE id NOT IN ({ids});"]
    for source in sources:
        row, passages = rows_of(source)
        out.append(f"DELETE FROM knowledge_source WHERE id = {literal(source.id)};")
        out.append(insert("knowledge_source", SOURCE_COLUMNS, row))
        out.extend(
            insert("knowledge_passage", PASSAGE_COLUMNS, {**p, "source_id": source.id}) for p in passages
        )
    return out


def check(sources: list[Source]) -> list[str]:
    return [f"{s.path.name}: {problem}" for s in sources for problem in s.problems]


def report(sources: list[Source]) -> list[str]:
    lines = []
    for s in sources:
        if s.meta.get("status") == "draft":
            lines.append(f"unreviewed  {s.id}")
        if s.meta.get("status") == "published" and is_stale(s):
            lines.append(f"stale       {s.id} (retrieved {s.meta.get('retrieved_at')})")
        if s.meta.get("status") == "retired":
            lines.append(f"retired     {s.id}")
    return lines


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "check"
    sources = load_all(Path(argv[argv.index("--dir") + 1]) if "--dir" in argv else SOURCES)
    if problems := check(sources):
        print("\n".join(problems), file=sys.stderr)
        return 1
    if command == "sql":
        print("\n".join(statements(sources)))
    elif command == "report":
        print("\n".join(report(sources)) or "Nothing stale or unreviewed.")
    else:
        print(f"{len(sources)} sources are sound.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
