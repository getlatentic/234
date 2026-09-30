# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where to cut the conversation: what is summarised, and what stays in front of the model word for word.

The messages after a cut are kept, so the cut must fall where nothing is torn:

- a reply and the results of its tool calls stay on the same side (a call still waiting for its result
  pins its reply and everything after it);
- every message on one side has lower seqs than every message on the other, so "after the cut" is one seq;
- the flow of the latest open quote stays whole, from the reply that made it;
- at least `keep_recent_tokens` are kept, and the cut falls where a person's message starts when it can.
"""

from dataclasses import dataclass

from .. import messages
from ..eventlog import Event
from ..messages import Unit
from ..tokens import corrected, message_tokens
from .quotes import open_floor

MIN_COVERED_TOKENS = 300


@dataclass(frozen=True)
class Cut:
    """The events from `first` to `last` are summarised; those after `last` are kept."""

    first: int
    last: int
    covered_tokens: int


@dataclass(frozen=True)
class Trim:
    """What the fallback does: cut (when it cuts) and the seq before which bulky results are stubbed."""

    cut: Cut | None
    pruned_before: int


def unit_tokens(unit: Unit, ratio: float) -> int:
    return corrected(sum(message_tokens(m) for m in unit.messages), ratio)


def live_units(events: list[Event], pruned_before: int = 0) -> tuple[list[Unit], int]:
    """The units after the latest cut, and the seq at which the next compaction's range begins."""
    compaction = messages.latest_compaction(events)
    cut = compaction.cut if compaction else 0
    return [u for u in messages.units_of(events, pruned_before) if u.first >= cut], cut or 1


def _sums(units: list[Unit], ratio: float) -> list[int]:
    """The tokens of units[i:], for every i; the last entry is 0."""
    tokens = [0]
    for unit in reversed(units):
        tokens.append(tokens[-1] + unit_tokens(unit, ratio))
    return tokens[::-1]


def _seq_of_cut(units: list[Unit]) -> dict[int, int]:
    """For every index where the conversation can be cut without tearing it, the seq from which all after is
    kept. A cut is whole when every message before it has lower seqs than every message after it."""
    suffix_first = [units[-1].first] if units else []
    for unit in reversed(units[:-1]):
        suffix_first.append(min(unit.first, suffix_first[-1]))
    suffix_first.reverse()
    cuts, prefix_last = {}, units[0].last if units else 0
    for index in range(1, len(units)):
        if prefix_last < suffix_first[index]:
            cuts[index] = suffix_first[index]
        prefix_last = max(prefix_last, units[index].last)
    return cuts


def _cut_at(seq: int, first: int, covered_tokens: int) -> Cut:
    return Cut(first, seq - 1, covered_tokens)


def choose_cut(
    events: list[Event],
    keep_recent_tokens: int,
    now_ms: int,
    ratio: float = 1.0,
    least_covered_tokens: int = MIN_COVERED_TOKENS,
) -> Cut | None:
    """The latest cut that keeps at least `keep_recent_tokens`, keeps the latest open quote whole and leaves
    something worth summarising. Among cuts at the start of a person's message, else among all."""
    units, first = live_units(events)
    tokens, cuts = _sums(units, ratio), _seq_of_cut(units)
    floor = open_floor(events, now_ms)
    fits = [
        i
        for i, seq in cuts.items()
        if tokens[i] >= keep_recent_tokens
        and (floor is None or seq <= floor)
        and tokens[0] - tokens[i] >= least_covered_tokens
    ]
    turn_starts = [i for i in fits if units[i].turn_start]
    chosen = max(turn_starts or fits, default=None)
    return None if chosen is None else _cut_at(cuts[chosen], first, tokens[0] - tokens[chosen])


def _recent_start(units: list[Unit], keep_recent_tokens: int, ratio: float) -> int:
    """The seq from which the units add up to `keep_recent_tokens`, or 0 when they never do."""
    total = 0
    for unit in reversed(units):
        total += unit_tokens(unit, ratio)
        if total >= keep_recent_tokens:
            return unit.first
    return 0


def trim(
    events: list[Event],
    reserved_tokens: int,
    target_tokens: int,
    keep_recent_tokens: int,
    now_ms: int,
    ratio: float,
) -> Trim:
    """The fallback: no summary can be had, so stub the bulky results older than the recent window, and when
    that is not enough drop the oldest messages, as few as will fit `target_tokens` beside `reserved_tokens`
    (what the request carries apart from the conversation). The latest open quote is kept while it can be."""
    units, first = live_units(events)
    pruned_before = _recent_start(units, keep_recent_tokens, ratio)
    units, _ = live_units(events, pruned_before)
    tokens, cuts = _sums(units, ratio), _seq_of_cut(units)
    if reserved_tokens + tokens[0] <= target_tokens:
        return Trim(None, pruned_before)
    floor = open_floor(events, now_ms)
    for respect_floor in (True, False):
        fitting = [
            i
            for i, seq in cuts.items()
            if reserved_tokens + tokens[i] <= target_tokens
            and (not respect_floor or floor is None or seq <= floor)
        ]
        if fitting:
            turn_starts = [i for i in fitting if units[i].turn_start]
            chosen = min(turn_starts or fitting)
            return Trim(_cut_at(cuts[chosen], first, tokens[0] - tokens[chosen]), pruned_before)
    if cuts:
        chosen = max(cuts)
        return Trim(_cut_at(cuts[chosen], first, tokens[0] - tokens[chosen]), pruned_before)
    return Trim(None, pruned_before)
