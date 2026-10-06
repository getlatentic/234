# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT §3.2: the personal-agent JWT. ES256 or RS256 and nothing else, signed by a key in the registered
agent's JWKS, `iss` the registered issuer, `aud` this host's audience, a `sub` that names the User, issued at
most 30 s in the future and living at most 300 s. The User is the pair (agent, sub)."""

import base64
import hashlib
import json
from dataclasses import dataclass

from accounts import rs256

from . import es256
from .agents import keys_of, registry
from .jwks import KeysUnavailable

ALGORITHMS = ("ES256", "RS256")
SKEW_SECONDS = 30
MAX_LIFETIME_SECONDS = 300
MAX_TOKEN_BYTES = 8 * 1024
OWNER_PREFIX = "p:"


class Refused(Exception):
    """The token is not accepted; the caller is told only 401."""


@dataclass(frozen=True)
class Caller:
    issuer: str
    sub: str

    @property
    def owner(self) -> str:
        """The chat owner for this User: one per (agent, sub), as opaque as `sub`."""
        digest = hashlib.sha256(f"{self.issuer}\n{self.sub}".encode()).hexdigest()
        return f"{OWNER_PREFIX}{digest[:32]}"


def _part(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _decoded(token: str) -> tuple[dict, dict, bytes, bytes]:
    if len(token) > MAX_TOKEN_BYTES or token.count(".") != 2:
        raise Refused("not a compact JWS")
    head, body, signature = token.split(".")
    try:
        header, claims = json.loads(_part(head)), json.loads(_part(body))
        return header, claims, f"{head}.{body}".encode(), _part(signature)
    except ValueError as error:
        raise Refused("not JSON") from error


def _signed_by_agent(header: dict, issuer: str, signed: bytes, signature: bytes) -> None:
    if header.get("alg") not in ALGORITHMS or not isinstance(header.get("kid"), str):
        raise Refused("algorithm or key id")
    try:
        key = keys_of(issuer).get(header["kid"])
    except KeysUnavailable as error:
        raise Refused("the agent's keys could not be read") from error
    if key is None or key.alg != header["alg"]:
        raise Refused("unknown key")
    good = (
        es256.verify(signed, signature, key.a, key.b)
        if key.alg == "ES256"
        else rs256.verify(signed, signature, key.a, key.b)
    )
    if not good:
        raise Refused("bad signature")


def _claims_hold(claims: dict, audience: str, now: float) -> None:
    iat, exp, sub = claims.get("iat"), claims.get("exp"), claims.get("sub")
    if claims.get("aud") != audience:
        raise Refused("audience")
    if not isinstance(sub, str) or not sub or len(sub) > 256:
        raise Refused("sub")
    if not all(isinstance(t, int | float) and not isinstance(t, bool) for t in (iat, exp)):
        raise Refused("iat and exp")
    if iat > now + SKEW_SECONDS or exp < now - SKEW_SECONDS or exp - iat > MAX_LIFETIME_SECONDS:
        raise Refused("time")


def caller_of(authorization: str, audience: str, now: float) -> Caller:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip() or not audience:
        raise Refused("no bearer token")
    header, claims, signed, signature = _decoded(token.strip())
    issuer = claims.get("iss")
    agent = registry().get(issuer) if isinstance(issuer, str) else None
    if agent is None or not agent.enabled:
        raise Refused("unknown or disabled agent")
    _signed_by_agent(header, issuer, signed, signature)
    _claims_hold(claims, audience, now)
    return Caller(issuer, claims["sub"])
