# SPDX-License-Identifier: AGPL-3.0-or-later
"""The options a line chooses from an offer's option groups: every id must be one the offer lists, once, and
every group takes as many as it allows."""

from ..errors import DomainError
from ..money import format_naira
from .model import Choice, Offer, OptionGroup


def _group_of(offer: Offer, choice_id: str) -> tuple[OptionGroup, Choice] | None:
    for group in offer.option_groups:
        for choice in group.choices:
            if choice.id == choice_id:
                return group, choice
    return None


def _wording(group: OptionGroup) -> str:
    listed = ", ".join(f"{c.id} ({c.label}, +{format_naira(c.delta_kobo)})" for c in group.choices)
    return f"{group.id}: {listed}"


def chosen(offer: Offer, options: tuple[str, ...]) -> tuple[Choice, ...]:
    """The choices an offer's line takes, or the reason it cannot."""
    if len(set(options)) != len(options):
        raise DomainError("OPTION_INVALID", f"{offer.name}: an option is named twice.")
    counts = {group.id: 0 for group in offer.option_groups}
    picked: list[Choice] = []
    for option in options:
        found = _group_of(offer, option)
        if found is None:
            raise DomainError(
                "OPTION_INVALID", f'{offer.name} has no option "{option}". find_items lists its options.'
            )
        group, choice = found
        counts[group.id] += 1
        picked.append(choice)
    for group in offer.option_groups:
        if not group.least <= counts[group.id] <= group.most:
            raise DomainError(
                "OPTION_INVALID",
                f"{offer.name} needs {group.least} to {group.most} of its {group.label} options. "
                f"Pass the ids of: {_wording(group)}.",
            )
    return tuple(picked)
