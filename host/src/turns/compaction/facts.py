# SPDX-License-Identifier: AGPL-3.0-or-later
"""The facts a summary must not lose, found without a model, and the check that a summary kept them.

A summary written by a model can drop a digit or round an amount, and what it drops is money: an amount, the
number money was sent to, the account it went to, the quote still waiting to be approved. So the facts are
read out of the log by rules (what the person typed, and what the connectors quoted), the summary is checked
for each of them, and when the model cannot be made to keep them they are written into the summary by the
same rules.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from .. import kinds
from ..eventlog import Event
from .quotes import QuoteFact, quotes_of

FACTS_HEADING = "## Facts recorded mechanically"
LISTED_QUOTES = 25
_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_QUOTE_ID = re.compile(r"\bqt-[0-9a-f]{8,}\b")
_NAIRA = re.compile(rf"(?:₦|(?<![A-Za-z])N(?=\s?\d)|\bNGN\s?)\s?({_NUMBER})(?:\s?([kK])\b)?")
_THOUSANDS = re.compile(rf"\b({_NUMBER})\s?([kK])\b")
_WORDED = re.compile(rf"\b({_NUMBER})\s*(?:naira|ngn)\b", re.IGNORECASE)
_KOBO = re.compile(r"\b(\d[\d,]*)\s*kobo\b", re.IGNORECASE)
_BARE = re.compile(_NUMBER)
_PHONE = re.compile(r"(?<!\d)(?:\+?234[\s-]?|0)[789][01]\d[\s-]?\d{3}[\s-]?\d{4}(?!\d)")
_ACCOUNT = re.compile(r"(?<!\d)(?:\d{10}|\d{4}[\s-]\d{3}[\s-]\d{3}|\d{3}[\s-]\d{3}[\s-]\d{4})(?!\d)")


@dataclass(frozen=True)
class Facts:
    """`amounts` are kobo; `phones` and `accounts` are ten digits (a phone without its leading 0 or +234)."""

    amounts: frozenset[int] = frozenset()
    phones: frozenset[str] = frozenset()
    accounts: frozenset[str] = frozenset()
    open_quotes: frozenset[str] = frozenset()

    def __or__(self, other: Facts) -> Facts:
        return Facts(
            self.amounts | other.amounts,
            self.phones | other.phones,
            self.accounts | other.accounts,
            self.open_quotes | other.open_quotes,
        )

    def __sub__(self, other: Facts) -> Facts:
        return Facts(
            self.amounts - other.amounts,
            self.phones - other.phones,
            self.accounts - other.accounts,
            self.open_quotes - other.open_quotes,
        )

    def __bool__(self) -> bool:
        return bool(self.amounts or self.phones or self.accounts or self.open_quotes)

    def lines(self) -> list[str]:
        """The facts as a list a person or a model can check against."""
        found = []
        if self.amounts:
            found.append("amounts: " + ", ".join(naira(k) for k in sorted(self.amounts)))
        if self.phones:
            found.append("phone numbers: " + ", ".join(f"0{p}" for p in sorted(self.phones)))
        if self.accounts:
            found.append("account numbers: " + ", ".join(sorted(self.accounts)))
        if self.open_quotes:
            found.append("quotes still open: " + ", ".join(sorted(self.open_quotes)))
        return found


def naira(kobo: int) -> str:
    whole, part = divmod(kobo, 100)
    return f"₦{whole:,}" + (f".{part:02d}" if part else "")


def _kobo_of(number: str, thousands: bool) -> int:
    value = Decimal(number.replace(",", "").rstrip(".")) * (1000 if thousands else 1)
    return int(value * 100)


def _amounts(text: str) -> set[int]:
    found = {_kobo_of(m[1], bool(m[2])) for m in _NAIRA.finditer(text)}
    found |= {_kobo_of(m[1], True) for m in _THOUSANDS.finditer(text)}
    found |= {_kobo_of(m[1], False) for m in _WORDED.finditer(text)}
    return found | {int(m[1].replace(",", "")) for m in _KOBO.finditer(text)}


def _phones(text: str) -> set[str]:
    return {re.sub(r"\D", "", m.group())[-10:] for m in _PHONE.finditer(text)}


def _accounts(text: str) -> set[str]:
    without_phones = _PHONE.sub(" ", text)
    return {re.sub(r"\D", "", m.group()) for m in _ACCOUNT.finditer(without_phones)}


def facts_in_text(text: str) -> Facts:
    text = _QUOTE_ID.sub(" ", text)
    return Facts(frozenset(_amounts(text)), frozenset(_phones(text)), frozenset(_accounts(text)))


def _spoken_in(summary: str) -> Facts:
    """What a summary says, read generously: a bare number is taken for naira, since a summary writes
    `500` where the person wrote `₦500`."""
    text = _QUOTE_ID.sub(" ", summary)
    bare = {_kobo_of(m.group(), False) for m in _BARE.finditer(text)}
    return Facts(frozenset(_amounts(text) | bare), frozenset(_phones(text)), frozenset(_accounts(text)))


def facts_of_events(events: list[Event]) -> Facts:
    """What the person typed and what the connectors quoted in these events."""
    found = Facts()
    for event in events:
        if event.type == kinds.USER:
            found |= facts_in_text(event.payload.get("text", ""))
    for quote in quotes_of(events):
        text = quote.what
        found |= facts_in_text(text) | Facts(
            amounts=frozenset({quote.kobo} if quote.kobo is not None else ())
        )
    return found


def missing_from(summary: str, required: Facts, kept_verbatim: Facts) -> Facts:
    """The required facts that the summary does not state and the events kept after it do not hold."""
    said = _spoken_in(summary)
    said |= Facts(open_quotes=frozenset(q for q in required.open_quotes if q in summary))
    return required - said - kept_verbatim


def _quote_line(quote: QuoteFact, open_now: bool) -> str:
    amount = naira(quote.kobo) if quote.kobo is not None else "amount unknown"
    state = f"{quote.phase} (open)" if open_now else quote.phase
    return f"- {quote.ref}: {state}, {amount}" + (f", {quote.what}" if quote.what else "")


def facts_block(events: list[Event], last: int, now_ms: int) -> str:
    """The facts of the events up to seq `last` written out by rule: every amount, number and quote with the
    state it is in now."""
    facts = facts_of_events([e for e in events if e.seq <= last])
    quotes = [q for q in quotes_of(events) if q.seq <= last]
    lines = [FACTS_HEADING, *facts.lines()]
    ranked = sorted(quotes, key=lambda q: (not q.is_open(now_ms), -q.seq))
    if ranked:
        lines.append("quotes:")
        lines += [_quote_line(q, q.is_open(now_ms)) for q in ranked[:LISTED_QUOTES]]
    if len(ranked) > LISTED_QUOTES:
        states: dict[str, int] = {}
        for quote in ranked[LISTED_QUOTES:]:
            states[quote.phase] = states.get(quote.phase, 0) + 1
        lines.append(
            f"- {len(ranked) - LISTED_QUOTES} earlier quotes: "
            + ", ".join(f"{n} {phase}" for phase, n in sorted(states.items()))
        )
    return "\n".join(lines) if len(lines) > 1 else ""


def without_block(summary: str) -> str:
    return summary.split(FACTS_HEADING)[0].rstrip()
