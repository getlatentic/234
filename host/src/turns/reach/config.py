# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which Brands 234 may reach for people, chosen by the owner (PACT_REACH), and the agent's own key and
issuer (PACT_AGENT_KEY, PUBLIC_BASE_URL). Without all three the connector does not exist."""

import json
from dataclasses import dataclass

from signatures.ec_key import EcPrivateKey
from signatures.private_key import from_jwk
from signatures.rsa_key import PrivateKey

SERVER = "brands"


@dataclass(frozen=True)
class Reached:
    card_url: str
    audience: str
    """The audience the Brand's Provider assigned 234 when it registered."""


@dataclass(frozen=True)
class ReachSettings:
    issuer: str
    key: PrivateKey | EcPrivateKey
    reached: tuple[Reached, ...]


class BadReach(ValueError):
    """PACT_REACH is a JSON list of {"card", "audience"}, each an http(s) URL and a non-empty string."""


def reached_of(text: str) -> tuple[Reached, ...]:
    try:
        listed = json.loads(text)
        found = tuple(Reached(str(entry["card"]), str(entry["audience"])) for entry in listed)
    except (ValueError, KeyError, TypeError) as error:
        raise BadReach(str(error)) from error
    if not all(r.card_url.startswith(("https://", "http://")) and r.audience for r in found):
        raise BadReach("each card is an http(s) URL with an audience")
    return found


def reach_settings(issuer: str, key_text: str, reach_text: str) -> ReachSettings | None:
    if not (issuer and key_text and reach_text):
        return None
    return ReachSettings(issuer.rstrip("/"), from_jwk(key_text), reached_of(reach_text))
