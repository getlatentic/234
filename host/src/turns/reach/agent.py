# SPDX-License-Identifier: AGPL-3.0-or-later
"""234's identity as a personal agent (PACT §3.2): a short JWT per request, signed with the agent's key
and naming the person by a `sub` of their own at each Brand. The `sub` is a digest of the Brand's card and the
person's ledger key: stable for them, different at every Brand, and nothing a Brand can turn back into who
they are or match with another Brand's."""

import hashlib
import secrets

from signatures import jws

from .config import ReachSettings

LIFETIME_SECONDS = 120


def sub_for(owner: str, card_url: str) -> str:
    return hashlib.sha256(f"234-pact-sub\n{card_url}\n{owner}".encode()).hexdigest()[:32]


def token(settings: ReachSettings, audience: str, sub: str, now: int) -> str:
    claims = {"iss": settings.issuer, "sub": sub, "aud": audience, "iat": now, "exp": now + LIFETIME_SECONDS}
    return jws.encode({**claims, "jti": secrets.token_urlsafe(12)}, settings.key)
