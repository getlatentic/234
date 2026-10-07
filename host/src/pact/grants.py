# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT §5.3 and §5.4: a grant, and the tokens it is used through. An access token is a delegation token the
host signs, for an hour at most; a refresh token works once, within the grant's 30 days, for the same User
of the same agent. A refresh token used twice ends its grant: one of the two holders is not the agent."""

import hashlib
import secrets
from typing import Any

from config.sql import returning

from . import addresses, signing
from .brands import Brand
from .errors import OAuthRefused
from .identity import Caller
from .models import Grant, RefreshToken

ACCESS_SECONDS = 3600
GRANT_SECONDS = 30 * 24 * 3600


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def make(brand: Brand, pa_issuer: str, pa_owner: str, account: str, scopes: str, now: int) -> Grant:
    return Grant.objects.create(
        id=f"pg_{secrets.token_hex(16)}",
        brand=brand.id,
        pa_issuer=pa_issuer,
        pa_owner=pa_owner,
        account=account,
        scopes=scopes,
        created_at=now,
        expires_at=now + GRANT_SECONDS,
    )


def tokens(grant: Grant, brand: Brand, now: int) -> dict[str, Any]:
    """The token response for a grant: a fresh delegation token and a fresh refresh token."""
    expires = min(now + ACCESS_SECONDS, grant.expires_at)
    claims = {
        "iss": addresses.issuer(brand),
        "aud": addresses.interface_url(brand),
        "sub": grant.account,
        "client_id": grant.pa_issuer,
        "scope": grant.scopes,
        "grant_id": grant.id,
        "iat": now,
        "exp": expires,
    }
    refresh = f"rt_{secrets.token_urlsafe(32)}"
    RefreshToken.objects.create(digest=digest(refresh), grant=grant, expires_at=grant.expires_at)
    return {
        "token_type": "Bearer",
        "access_token": signing.sign(claims),
        "refresh_token": refresh,
        "expires_in": expires - now,
        "scope": grant.scopes,
    }


def refresh(brand: Brand, caller: Caller, token: str, now: int) -> dict[str, Any]:
    found = RefreshToken.objects.select_related("grant").filter(digest=digest(token)).first()
    grant = found.grant if found else None
    if grant is None or grant.brand != brand.id or grant.pa_owner != caller.owner:
        raise OAuthRefused("invalid_grant", "Unknown refresh token.")
    if found.expires_at <= now:
        raise OAuthRefused("invalid_grant", "The refresh token has expired.")
    claimed = returning(
        "UPDATE pact_refreshtoken SET used = 1 WHERE digest = %s AND used = 0 RETURNING grant_id",
        [found.digest],
    )
    if not claimed:
        Grant.objects.filter(id=grant.id).update(revoked=True)
        raise OAuthRefused("invalid_grant", "That refresh token was already used; the grant has ended.")
    if grant.revoked or grant.expires_at <= now:
        raise OAuthRefused("invalid_grant", "The grant has ended.")
    return tokens(grant, brand, now)


def of_account(account: str, now: int) -> list[Grant]:
    """The grants a person made that still work, the latest first."""
    live = Grant.objects.filter(account=account, revoked=False, expires_at__gt=now)
    return list(live.order_by("-created_at"))


def end(account: str, grant_id: str) -> None:
    """Ends one of the person's grants: its delegation tokens are refused from the next message, and its
    refresh tokens are gone."""
    Grant.objects.filter(id=grant_id, account=account).update(revoked=True)
    RefreshToken.objects.filter(grant_id=grant_id, grant__account=account).delete()
