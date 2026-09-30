# SPDX-License-Identifier: AGPL-3.0-or-later
"""Counts and intervals over scored draws. Pure."""

import math
import statistics
from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

Z95 = 1.959963984540054


def wilson(passes: int, draws: int, z: float = Z95) -> tuple[float, float]:
    """The Wilson score interval for a proportion; (0, 1) when there are no draws."""
    if draws == 0:
        return 0.0, 1.0
    p = passes / draws
    centre = (p + z * z / (2 * draws)) / (1 + z * z / draws)
    half = z * math.sqrt(p * (1 - p) / draws + z * z / (4 * draws * draws)) / (1 + z * z / draws)
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(passes: int, draws: int) -> str:
    """`12/15 80% [55-93]`."""
    low, high = wilson(passes, draws)
    share = 100 * passes / draws if draws else 0
    return f"{passes}/{draws} {share:.0f}% [{100 * low:.0f}-{100 * high:.0f}]"


def group_rates(
    draws: Iterable[dict[str, Any]],
    key: Callable[[dict[str, Any]], str],
    ok: Callable[[dict[str, Any]], bool],
) -> dict[str, tuple[int, int]]:
    """{group: (passes, draws)} in the order the groups first appear."""
    counts: dict[str, list[int]] = {}
    for draw in draws:
        passes_and_draws = counts.setdefault(key(draw), [0, 0])
        passes_and_draws[0] += ok(draw)
        passes_and_draws[1] += 1
    return {k: (v[0], v[1]) for k, v in counts.items()}


def cases_passing_every_draw(
    draws: Iterable[dict[str, Any]], ok: Callable[[dict[str, Any]], bool]
) -> tuple[int, int]:
    outcomes: dict[str, bool] = {}
    for draw in draws:
        outcomes[draw["case"]] = outcomes.get(draw["case"], True) and ok(draw)
    return sum(outcomes.values()), len(outcomes)


def tally(values: Iterable[str]) -> dict[str, int]:
    return dict(Counter(values).most_common())


def latency_summary(seconds: list[float]) -> str:
    if not seconds:
        return "no data"
    ordered = sorted(seconds)
    p90 = ordered[min(len(ordered) - 1, math.ceil(0.9 * len(ordered)) - 1)]
    median = statistics.median(ordered)
    return f"median {median:.1f} s, p90 {p90:.1f} s, max {ordered[-1]:.1f} s over {len(ordered)} turns"
