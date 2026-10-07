# SPDX-License-Identifier: AGPL-3.0-or-later
"""Codes and tokens: a code is used once within a minute and only with its PKCE verifier; an access token
lives an hour and is good for one resource; a refresh token is used once and replaced, and one used twice
ends every token of its grant (OAuth 2.1 section 4.3.1, refresh token rotation for public clients)."""

import base64
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass

from config.sql import returning

from .models import Client, Code, Token
from .resources import connector_of

CODE_SECONDS = 60
ACCESS_SECONDS = 3600
REFRESH_SECONDS = 30 * 24 * 3600
VERIFIER = re.compile(r"[A-Za-z0-9\-._~]{43,128}")
CHALLENGE = re.compile(r"[A-Za-z0-9\-_]{43}")


class InvalidGrant(Exception):
    """A code, verifier or refresh token that is refused; the client is told only `invalid_grant`."""


@dataclass(frozen=True)
class Request:
    """What an approved authorization request asked for."""

    client_id: str
    owner: str
    redirect_uri: str
    challenge: str
    resource: str
    scope: str


@dataclass(frozen=True)
class Access:
    """Whom a valid access token acts for, and where."""

    owner: str
    client_id: str
    resource: str
    scope: str


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now(now: float | None) -> int:
    return int(time.time() if now is None else now)


def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def issue_code(request: Request, now: float | None = None) -> str:
    code = f"234ac_{secrets.token_urlsafe(32)}"
    Code.objects.filter(expires_at__lt=_now(now)).delete()
    Code.objects.create(
        digest=digest(code),
        client_id=request.client_id,
        owner=request.owner,
        redirect_uri=request.redirect_uri,
        challenge=request.challenge,
        resource=request.resource,
        scope=request.scope,
        expires_at=_now(now) + CODE_SECONDS,
    )
    return code


def _tokens(family: str, request: Request, now: int) -> dict[str, object]:
    access, refresh = f"234at_{secrets.token_urlsafe(32)}", f"234rt_{secrets.token_urlsafe(32)}"
    Token.objects.filter(expires_at__lt=now).delete()
    common = {
        "family": family,
        "client_id": request.client_id,
        "owner": request.owner,
        "resource": request.resource,
        "scope": request.scope,
    }
    Token.objects.bulk_create(
        [
            Token(digest=digest(access), kind=Token.ACCESS, expires_at=now + ACCESS_SECONDS, **common),
            Token(digest=digest(refresh), kind=Token.REFRESH, expires_at=now + REFRESH_SECONDS, **common),
        ]
    )
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": ACCESS_SECONDS,
        "refresh_token": refresh,
        "scope": request.scope,
    }


def redeem_code(
    code: str,
    client_id: str,
    redirect_uri: str,
    verifier: str,
    resource: str | None,
    now: float | None = None,
) -> dict[str, object]:
    moment = _now(now)
    # One statement takes the code: it is single-use however many redemptions race.
    taken = returning(
        "DELETE FROM oauth_code WHERE digest = %s "
        "RETURNING client_id, owner, redirect_uri, challenge, resource, scope, expires_at",
        [digest(code)],
    )
    if not taken:
        raise InvalidGrant("unknown or used code")
    found = Request(*taken[0][:6])
    if taken[0][6] < moment:
        raise InvalidGrant("expired code")
    if found.client_id != client_id or found.redirect_uri != redirect_uri:
        raise InvalidGrant("code issued to another client or redirect")
    if resource is not None and resource.rstrip("/") != found.resource:
        raise InvalidGrant("code issued for another resource")
    if not VERIFIER.fullmatch(verifier) or not hmac.compare_digest(s256(verifier), found.challenge):
        raise InvalidGrant("PKCE verifier does not match")
    return _tokens(secrets.token_hex(16), found, moment)


def refresh(token: str, client_id: str, resource: str | None, now: float | None = None) -> dict[str, object]:
    moment = _now(now)
    claimed = returning(
        "UPDATE oauth_token SET used = 1 WHERE digest = %s AND kind = %s AND used = 0 "
        "RETURNING family, client_id, owner, resource, scope, expires_at",
        [digest(token), Token.REFRESH],
    )
    if not claimed:
        used = Token.objects.filter(digest=digest(token), kind=Token.REFRESH).first()
        if used is not None:
            Token.objects.filter(family=used.family).delete()
            raise InvalidGrant("refresh token used twice; its grant is ended")
        raise InvalidGrant("unknown refresh token")
    family, owner_client, owner, granted, scope, expires_at = claimed[0]
    if expires_at < moment or owner_client != client_id:
        raise InvalidGrant("expired refresh token or another client")
    if resource is not None and resource.rstrip("/") != granted:
        raise InvalidGrant("refresh token issued for another resource")
    return _tokens(family, Request(client_id, owner, "", "", granted, scope), moment)


def revoke(token: str) -> None:
    """RFC 7009: revoking either token of a grant ends the whole grant; an unknown token is not an error."""
    found = Token.objects.filter(digest=digest(token)).first()
    if found is not None:
        Token.objects.filter(family=found.family).delete()


def access_of(token: str, now: float | None = None) -> Access | None:
    found = Token.objects.filter(digest=digest(token), kind=Token.ACCESS).first()
    if found is None or found.expires_at < _now(now):
        return None
    return Access(found.owner, found.client_id, found.resource, found.scope)


@dataclass(frozen=True)
class Connected:
    """A client the person allowed, with the connectors its live tokens open."""

    client_id: str
    name: str
    connectors: tuple[str, ...]


def clients_of(owner: str, now: float | None = None) -> list[Connected]:
    live = Token.objects.filter(owner=owner, expires_at__gte=_now(now)).values_list("client_id", "resource")
    opened: dict[str, set[str]] = {}
    for client_id, resource in live:
        opened.setdefault(client_id, set()).add(connector_of(resource) or resource)
    names = dict(Client.objects.filter(client_id__in=opened).values_list("client_id", "name"))
    return [
        Connected(client_id, names.get(client_id, client_id), tuple(sorted(connectors)))
        for client_id, connectors in sorted(opened.items(), key=lambda item: names.get(item[0], item[0]))
    ]


def end_client(owner: str, client_id: str) -> None:
    """Ends every grant the person made to this client: its tokens stop working at once."""
    Token.objects.filter(owner=owner, client_id=client_id).delete()
    Code.objects.filter(owner=owner, client_id=client_id).delete()
