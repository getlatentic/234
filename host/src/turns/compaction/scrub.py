# SPDX-License-Identifier: AGPL-3.0-or-later
"""Text that may reach the summariser, and the summary that comes back: no link, no token, no key, no code and
no card number.

The approval token, the checkout link and a card's data are already kept out of the events the model reads.
This is the second wall: whatever the events hold, the summariser is fed without them and the summary is
stored without them, so a secret that got into a message is not copied into the model's memory.
"""

import re

from ..inputs import redact_card_numbers

LINK_REMOVED = "[link removed]"
REMOVED = "[removed]"
CARD_REMOVED = "[card number removed]"

_LINK = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_API_KEY = re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]+")
_LABELLED = re.compile(
    r"\b(?:approval[ _-]?token|access[ _-]?code|api[ _-]?key|secret|password|token)\b"
    r"[\"']?\s*[:=]\s*[\"']?[^\s\"',;]+",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer\s+\S{8,}", re.IGNORECASE)
_ONE_TIME_CODE = re.compile(
    r"\b(?:one[ -]time code|verification code|otp|pin)\b\W{0,3}(?:is\W{0,3})?\d{3,8}\b", re.IGNORECASE
)
_LONG_SECRET = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])")


def scrubbed(text: str, *, links: bool = False) -> str:
    """`text` without its secrets and, unless `links` keeps them, its links."""
    if not links:
        text = _LINK.sub(LINK_REMOVED, text)
    for pattern in (_API_KEY, _LABELLED, _BEARER, _ONE_TIME_CODE, _LONG_SECRET):
        text = pattern.sub(REMOVED, text)
    return redact_card_numbers(text, CARD_REMOVED)
