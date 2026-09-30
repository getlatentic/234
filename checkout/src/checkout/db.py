# SPDX-License-Identifier: AGPL-3.0-or-later
"""The database seam: the D1 binding inside a Worker, SQLite (sqlite_db.py) in unit tests.

Both answer the same four calls. A statement is atomic on its own; a batch is one transaction
(D1 runs a batch as an implicit transaction and rolls it back on the first failure).
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

Statement = tuple[str, tuple[Any, ...]]


@dataclass(frozen=True)
class StatementResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    changes: int = 0


class Db(Protocol):
    async def rows(self, sql: str, *params: Any) -> list[dict[str, Any]]: ...

    async def row(self, sql: str, *params: Any) -> dict[str, Any] | None: ...

    async def execute(self, sql: str, *params: Any) -> int:
        """Runs one statement and returns how many rows it changed."""
        ...

    async def batch(self, statements: list[Statement]) -> list[StatementResult]: ...


class UniqueViolation(Exception):
    """A UNIQUE or PRIMARY KEY constraint refused an insert."""


def _to_python(value: Any) -> Any:
    return value.to_py() if hasattr(value, "to_py") else value


def _is_unique_violation(error: Exception) -> bool:
    text = str(error)
    return (
        "UNIQUE constraint failed" in text
        or "SQLITE_CONSTRAINT_UNIQUE" in text
        or ("SQLITE_CONSTRAINT_PRIMARYKEY" in text)
    )


class D1(Db):
    """Wraps a D1 binding (`env.DB`). Python None is bound as JavaScript null."""

    def __init__(self, binding: Any) -> None:
        self._binding = binding

    @staticmethod
    def _null() -> Any:
        from js import JSON

        return JSON.parse("null")

    def _statement(self, sql: str, params: tuple[Any, ...]) -> Any:
        bound = tuple(self._null() if p is None else p for p in params)
        return self._binding.prepare(sql).bind(*bound)

    async def rows(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        answer = _to_python(await self._statement(sql, params).all())
        return list(answer["results"])

    async def row(self, sql: str, *params: Any) -> dict[str, Any] | None:
        found = await self.rows(sql, *params)
        return found[0] if found else None

    async def execute(self, sql: str, *params: Any) -> int:
        try:
            answer = await self._statement(sql, params).run()
        except Exception as error:
            if _is_unique_violation(error):
                raise UniqueViolation(str(error)) from error
            raise
        return int(_to_python(answer)["meta"]["changes"])

    async def batch(self, statements: list[Statement]) -> list[StatementResult]:
        prepared = [self._statement(sql, params) for sql, params in statements]
        answers = _to_python(await self._binding.batch(prepared))
        return [
            StatementResult(list(answer["results"]), int(answer["meta"]["changes"])) for answer in answers
        ]
