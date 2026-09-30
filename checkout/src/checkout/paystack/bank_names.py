# SPDX-License-Identifier: AGPL-3.0-or-later
"""Names to Paystack's bank codes. The model passes the bank as the person said it ("GTB", "Guaranty Trust",
"opay"); this table, built from Paystack's own list plus hand-written spellings, is the only thing that
turns it into a code. A name that is not exactly one bank is refused with the nearest banks, so the person
is asked; a code is never guessed.

Pure: no I/O, so the Worker builds the table once at startup and the evaluation's scorer can use it.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import NamedTuple

from .bank_aliases import BANK_ALIASES
from .bank_list import BANK_LIST

MAX_CANDIDATES = 3
MIN_SIMILARITY = 0.7
_GENERIC_WORDS = frozenset({"bank", "plc", "limited", "ltd"})


class Bank(NamedTuple):
    name: str
    code: str


class BankNotFound(Exception):
    """The name is no bank of the list. `candidates` are the nearest banks, best first."""

    def __init__(self, asked: str, candidates: tuple[Bank, ...]) -> None:
        super().__init__(asked)
        self.asked = asked
        self.candidates = candidates


class BankAmbiguous(BankNotFound):
    """The name fits several banks equally."""


def normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.replace("&", " and "))
    plain = "".join(c for c in folded if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def _without_generic_words(key: str) -> str:
    return " ".join(word for word in key.split() if word not in _GENERIC_WORDS)


def _compact(key: str) -> str:
    """A spelling with no spaces, so "U.B.A", "GT Bank" and "palm pay" meet "uba", "gtbank" and "palmpay"."""
    return key.replace(" ", "")


def _spellings_of(name: str, slug: str) -> set[str]:
    full = normalise(name)
    from_slug = normalise(slug).removesuffix(" ng")
    return {key for key in (full, _without_generic_words(full), from_slug) if key}


def _build() -> tuple[dict[str, Bank], dict[str, set[str]], dict[str, str], dict[str, set[str]]]:
    """The first bank of each code, the codes each derived spelling names, the code each hand-written
    spelling names, and every spelling of each code."""
    by_code: dict[str, Bank] = {}
    derived: dict[str, set[str]] = {}
    for name, code, slug, _ in BANK_LIST:
        by_code.setdefault(code, Bank(name, code))
        for key in _spellings_of(name, slug):
            derived.setdefault(_compact(key), set()).add(code)
    aliases = {_compact(normalise(word)): code for code, words in BANK_ALIASES.items() for word in words}
    keys_of_code: dict[str, set[str]] = {}
    for name, code, slug, _ in BANK_LIST:
        keys_of_code.setdefault(code, set()).update(_spellings_of(name, slug))
    for code, words in BANK_ALIASES.items():
        keys_of_code.setdefault(code, set()).update(normalise(word) for word in words)
    return by_code, derived, aliases, keys_of_code


_BY_CODE, _DERIVED, _ALIASES, _KEYS_OF_CODE = _build()


def bank_of_code(code: str) -> Bank | None:
    """The bank Paystack lists under this code (the first, where banks share one)."""
    return _BY_CODE.get(code)


def _contains(words: set[str], key: str) -> bool:
    return words <= set(key.split())


def _score(asked: str, words: set[str], code: str) -> float:
    keys = _KEYS_OF_CODE[code]
    if any(_contains(words, key) for key in keys):
        return 1.0
    core = _without_generic_words(asked) or asked
    return max(SequenceMatcher(None, core, _without_generic_words(key) or key).ratio() for key in keys)


def _nearest(asked: str) -> tuple[Bank, ...]:
    words = set(asked.split())
    scored = [(_score(asked, words, code), code) for code in _BY_CODE]
    known = sorted(
        (item for item in scored if item[0] >= MIN_SIMILARITY),
        key=lambda item: (-item[0], item[1] not in BANK_ALIASES, len(_BY_CODE[item[1]].name), item[1]),
    )
    return tuple(_BY_CODE[code] for _, code in known[:MAX_CANDIDATES])


def _containing(asked: str) -> set[str]:
    words = set(asked.split())
    return {code for code, keys in _KEYS_OF_CODE.items() if any(_contains(words, key) for key in keys)}


def resolve_bank(text: str) -> Bank:
    """The one bank this name is. Raises `BankAmbiguous` when it fits several, `BankNotFound` when it fits
    none exactly; both carry the nearest banks."""
    asked = normalise(text)
    if not asked:
        raise BankNotFound(text, ())
    compact = _compact(asked)
    if compact in _ALIASES:
        return _BY_CODE[_ALIASES[compact]]
    exact = _DERIVED.get(compact, set())
    if len(exact) == 1:
        return _BY_CODE[next(iter(exact))]
    if len(exact) > 1 or len(_containing(asked)) > 1:
        raise BankAmbiguous(text, _nearest(asked))
    raise BankNotFound(text, _nearest(asked))
