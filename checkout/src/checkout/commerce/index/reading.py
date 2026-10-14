# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading what Index answers. Its tools document the fields of their answers only in prose, so a number is
looked for under the names the prose uses, in kobo (`name_kobo`) or in naira (`name_naira`), at the top of the
answer or in a section of it (`breakdown`, `preview`, `summary`, `order`). An answer without what a caller
needs is not guessed at: the caller refuses, and nothing is charged."""

from typing import Any

from ...errors import DomainError
from ...money import KOBO_PER_NAIRA, Kobo
from ..text import third_party
from .wire import IndexMisread

SECTIONS = ("breakdown", "preview", "summary", "order", "result")
WORDS = 200


def flat(data: dict[str, Any]) -> dict[str, Any]:
    """The answer with the fields of its sections lifted to the top; a field at the top stands."""
    lifted: dict[str, Any] = {}
    for section in SECTIONS:
        if isinstance(data.get(section), dict):
            lifted.update(data[section])
    return {**lifted, **data}


def text_in(data: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = data.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def kobo_in(data: dict[str, Any], *names: str) -> Kobo | None:
    for name in names:
        kobo, naira = data.get(f"{name}_kobo"), data.get(f"{name}_naira")
        if isinstance(kobo, int) and not isinstance(kobo, bool) and kobo >= 0:
            return kobo
        if isinstance(naira, int | float) and not isinstance(naira, bool) and naira >= 0:
            return round(naira * KOBO_PER_NAIRA)
    return None


def need_kobo(data: dict[str, Any], what: str, *names: str) -> Kobo:
    found = kobo_in(data, *names)
    if found is None:
        raise IndexMisread(f"Index's answer did not say {what}.")
    return found


def whole_naira(kobo: Kobo) -> int:
    """Index takes naira; an amount with kobo in it is refused rather than rounded."""
    naira, rest = divmod(kobo, KOBO_PER_NAIRA)
    if rest:
        raise DomainError(
            "INVALID_INPUT", "Paystack Index takes whole naira. Ask for an amount without kobo."
        )
    return naira


def words(text: str, limit: int = WORDS) -> str:
    """Index's own words for a refusal, on one line and short, for a person or a model to read as data."""
    return third_party(text, limit)


def listing(data: dict[str, Any], *names: str) -> list[Any]:
    for name in names:
        if isinstance(data.get(name), list):
            return data[name]
    return []
