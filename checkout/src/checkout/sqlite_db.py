# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLite behind the Db seam, for unit tests: in-memory, built from the migrations.

A batch is one transaction, as on D1. A single statement commits on its own. Every call first hands
control back to the event loop, so callers running together interleave between statements the way
requests do on D1; a rule that reads and then writes shows up as a failing test here.
"""

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

from .db import Db, Statement, StatementResult, UniqueViolation

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def all_migrations() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


class SqliteDb(Db):
    def __init__(self, migrations: list[Path] | None = None) -> None:
        """Built from every migration, or from the given ones (a test that stops halfway, adds rows and
        applies the rest, as a deployed database does)."""
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        for migration in all_migrations() if migrations is None else migrations:
            self.migrate(migration)

    def migrate(self, migration: Path) -> None:
        self.connection.executescript(migration.read_text())

    def _run(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Cursor:
        try:
            return self.connection.execute(sql, params)
        except sqlite3.IntegrityError as error:
            if "UNIQUE" in str(error) or "PRIMARY KEY" in str(error):
                raise UniqueViolation(str(error)) from error
            raise

    async def rows(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        await asyncio.sleep(0)
        return [dict(row) for row in self._run(sql, params).fetchall()]

    async def row(self, sql: str, *params: Any) -> dict[str, Any] | None:
        found = await self.rows(sql, *params)
        return found[0] if found else None

    async def execute(self, sql: str, *params: Any) -> int:
        await asyncio.sleep(0)
        return self._run(sql, params).rowcount

    async def batch(self, statements: list[Statement]) -> list[StatementResult]:
        await asyncio.sleep(0)
        self.connection.execute("BEGIN")
        try:
            answers = []
            for sql, params in statements:
                cursor = self._run(sql, params)
                answers.append(StatementResult([dict(r) for r in cursor.fetchall()], max(cursor.rowcount, 0)))
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return answers
