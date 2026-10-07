# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Brands this host serves to personal agents (PACT §1): 234 itself with every connector, and any Brand
the owner adds in PACT_BRANDS with the connectors it may use. A Brand's chats offer the model its connectors
and no others."""

import json
import re
from dataclasses import dataclass
from functools import cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from turns.permissions import scopes_of

BRAND_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
DEFAULT = {
    "234": {
        "name": "234",
        "description": "Buy airtime and data, send money, order food and pay merchants in Nigeria. "
        "The person approves every payment.",
    }
}


@dataclass(frozen=True)
class Brand:
    id: str
    name: str
    description: str
    connectors: tuple[str, ...]

    @property
    def scopes(self) -> dict[str, str]:
        """What a personal agent may ask to do as the person's account here, and the words consent shows."""
        return scopes_of(self.connectors)


@cache
def brands() -> dict[str, Brand]:
    try:
        listed = json.loads(settings.PACT_BRANDS) if settings.PACT_BRANDS else DEFAULT
        found = {
            brand_id: Brand(
                brand_id,
                str(entry["name"]),
                str(entry.get("description", "")),
                tuple(entry.get("connectors") or settings.CONNECTORS),
            )
            for brand_id, entry in listed.items()
        }
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ImproperlyConfigured(
            "PACT_BRANDS is a JSON object of brandId: {name, description, connectors}."
        ) from error
    unknown = {c for b in found.values() for c in b.connectors} - set(settings.CONNECTORS)
    if unknown or not all(BRAND_ID.fullmatch(b) for b in found):
        raise ImproperlyConfigured(
            f"PACT_BRANDS names unknown connectors or a bad brand id: {sorted(unknown)}"
        )
    return found
