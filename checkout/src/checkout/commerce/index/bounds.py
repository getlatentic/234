# SPDX-License-Identifier: AGPL-3.0-or-later
"""What one order through Index may come to: Index's own bounds (the tool descriptions of 2026-10-13: airtime
₦50 to ₦5,000, electricity ₦1,000 to ₦1,000,000; ₦100,000 is Index's published cap on a food order), and below
them 234's cap for the kind (settings.py). Both are the merchant's limits, so an order outside them is refused
before Index is called (commerce/pricing.py)."""

from ...money import Kobo
from .settings import IndexSettings

INDEX_BOUNDS_KOBO: dict[str, tuple[Kobo, Kobo]] = {
    "airtime": (5_000, 500_000),
    "electricity": (100_000, 100_000_000),
    "food": (50_000, 10_000_000),
}


def limits_for(kind: str, settings: IndexSettings) -> tuple[Kobo, Kobo]:
    """The least and the most, in kobo, for one order of this kind."""
    least, most = INDEX_BOUNDS_KOBO[kind]
    return least, max(least, min(most, settings.caps_kobo.get(kind, most)))
