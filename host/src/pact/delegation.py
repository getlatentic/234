# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT §5.5: the delegation token a personal agent sends next to its own JWT. It is accepted only when this
host signed it for this Brand's interface, it has not expired, its `client_id` is the agent that sends it,
and its grant is live and was made for this very User of that agent. It then names the account the message
runs as and the scopes it may use."""

from dataclasses import dataclass

from django.conf import settings

from . import addresses, signing
from .brands import Brand
from .identity import SKEW_SECONDS, Caller
from .models import Grant

HEADER = "X-A2A-User-Delegation"


class Rejected(Exception):
    """A delegation token that is not accepted: 401 with error="invalid_token", no A2A body."""


@dataclass(frozen=True)
class Delegation:
    grant_id: str
    account: str
    scopes: frozenset[str]


def offered(brand: Brand) -> bool:
    """A Brand offers delegation when people can sign in to 234, the host can sign, and it has scopes."""
    return settings.SIGN_IN_ENABLED and signing.enabled() and bool(brand.scopes)


def _claims_hold(claims: dict, brand: Brand, caller: Caller, now: float) -> bool:
    iat, exp = claims.get("iat"), claims.get("exp")
    times = all(isinstance(t, int) and not isinstance(t, bool) for t in (iat, exp))
    return (
        times
        and iat <= now + SKEW_SECONDS
        and now < exp
        and claims.get("iss") == addresses.issuer(brand)
        and claims.get("aud") == addresses.interface_url(brand)
        and claims.get("client_id") == caller.issuer
        and all(isinstance(claims.get(name), str) for name in ("sub", "scope", "grant_id"))
    )


def delegation_of(header: str, brand: Brand, caller: Caller, now: float) -> Delegation:
    scheme, _, token = header.partition(" ")
    if not offered(brand) or scheme.lower() != "bearer" or not token.strip():
        raise Rejected("not a bearer delegation token")
    claims = signing.verified(token.strip())
    if claims is None or not _claims_hold(claims, brand, caller, now):
        raise Rejected("signature or claims")
    grant = Grant.objects.filter(
        id=claims["grant_id"], brand=brand.id, pa_owner=caller.owner, account=claims["sub"], revoked=False
    ).first()
    if grant is None or grant.expires_at <= now:
        raise Rejected("no live grant for this User")
    scopes = frozenset(claims["scope"].split()) & frozenset(grant.scopes.split())
    return Delegation(grant.id, grant.account, scopes)
