# SPDX-License-Identifier: AGPL-3.0-or-later
"""The database seam: the D1 binding inside a Worker, SQLite in unit tests (tests/support.py).

A statement is atomic on its own; a batch is one transaction.
"""

from typing import Any, Protocol


class Db(Protocol):
    async def rows(self, sql: str, *params: Any) -> list[dict[str, Any]]: ...

    async def row(self, sql: str, *params: Any) -> dict[str, Any] | None: ...

    async def execute(self, sql: str, *params: Any) -> int:
        """Runs one statement and returns how many rows it changed."""
        ...


class UniqueViolation(Exception):
    """A UNIQUE or PRIMARY KEY constraint refused an insert."""


def _to_python(value: Any) -> Any:
    return value.to_py() if hasattr(value, "to_py") else value


def _is_unique_violation(error: Exception) -> bool:
    text = str(error)
    return (
        "UNIQUE constraint failed" in text
        or "SQLITE_CONSTRAINT_UNIQUE" in text
        or "SQLITE_CONSTRAINT_PRIMARYKEY" in text
    )


class D1(Db):
    """Wraps a D1 binding (`env.DB`). Python None is bound as JavaScript null."""

    def __init__(self, binding: Any) -> None:
        self._binding = binding

    def _statement(self, sql: str, params: tuple[Any, ...]) -> Any:
        from js import JSON

        null = JSON.parse("null")
        return self._binding.prepare(sql).bind(*[null if p is None else p for p in params])

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
