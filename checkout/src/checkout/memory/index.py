# SPDX-License-Identifier: AGPL-3.0-or-later
"""The memory index: the text the host puts in front of the model at the start of every turn. It is rendered
here, by one function, from rows read in one query. It is not a file, and nothing is stored in this form.

    ## Recipients
    - [Mum](3f2a9c0b1d4e5f60) — GTBank, Ada Okafor, ends 6789
    ## Preferences
    - [Usual airtime](...) — MTN, 500 naira
    ## Facts
    - [Lives in](...) — Yaba, Lagos
    3 more: use recall

Groups come in a fixed order, the entries of a group newest use first. The index holds titles and hooks only;
a body is fetched by `recall`. When the budget runs out, the entries that do not fit are counted in the last
line, so the model knows to look."""

from collections.abc import Iterable
from typing import Any

from .entry import KINDS

HEADINGS = {"recipient": "## Recipients", "preference": "## Preferences", "fact": "## Facts"}
CHARS_PER_TOKEN = 4


def tokens_of(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


def line_of(row: dict[str, Any]) -> str:
    return f"- [{row['title']}]({row['id']}) — {row['hook']}"


def omitted_line(count: int) -> str:
    return f"{count} more: use recall"


def _entries(rows: Iterable[dict[str, Any]]) -> list[tuple[list[str], dict[str, Any]]]:
    """Every row in index order, each with the heading it opens a group with (none for the rest)."""
    by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
    for row in rows:
        by_kind[row["kind"]].append(row)
    return [
        ([HEADINGS[kind]] if at == 0 else [], row) for kind in KINDS for at, row in enumerate(by_kind[kind])
    ]


def render_index(rows: Iterable[dict[str, Any]], budget_tokens: int) -> str:
    """The index of `rows` (id, kind, title, hook), most recently used first, within the token budget. Empty
    when there are no rows."""
    entries = _entries(rows)
    lines: list[str] = []
    used = shown = 0
    for heading, row in entries:
        block = [*heading, line_of(row)]
        cost = tokens_of("\n".join(block)) + 1
        left = len(entries) - shown - 1
        reserve = tokens_of(omitted_line(left)) + 1 if left else 0
        if used + cost + reserve > budget_tokens:
            break
        lines += block
        used += cost
        shown += 1
    if shown < len(entries):
        lines.append(omitted_line(len(entries) - shown))
    return "\n".join(lines)
