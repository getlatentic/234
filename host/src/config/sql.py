# SPDX-License-Identifier: AGPL-3.0-or-later
"""Statements whose rows say what they did. On D1, Django's row counts are not the number of rows changed: a
write that touches nothing reports -1 and one that does reports D1's rows_written, which counts index entries
too. So a rule that turns on "did this change a row" reads the rows the statement returns instead."""

from typing import Any

from django.db import connection


def returning(sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()
