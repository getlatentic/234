# SPDX-License-Identifier: AGPL-3.0-or-later
"""The host's own key for PACT Delegated (§5.4, §5.6): it signs delegation tokens and receipts with RS256,
and its public half is the JWKS the authorization server metadata names. PACT_SIGNING_KEY holds the private
key as an RSA JWK (tools/pact-key.mjs makes one)."""

from functools import cache
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from signatures import jws
from signatures.jwks import Key
from signatures.rsa_key import BadKey, PrivateKey, from_jwk


def enabled() -> bool:
    return bool(settings.PACT_SIGNING_KEY)


@cache
def key() -> PrivateKey:
    try:
        return from_jwk(settings.PACT_SIGNING_KEY)
    except BadKey as error:
        raise ImproperlyConfigured(f"PACT_SIGNING_KEY must be {error}.") from error


def jwks() -> dict[str, list[dict[str, str]]]:
    return {"keys": [key().public()]}


def sign(claims: dict[str, Any]) -> str:
    return jws.encode(claims, key())


def verified(token: str) -> dict[str, Any] | None:
    """The claims of a JWS this host signed, or None for anything else."""
    found, mine = jws.parts(token), key()
    if found is None or found.header.get("kid") != mine.kid:
        return None
    return found.claims if jws.signed_by(found, Key("RS256", mine.n, mine.e)) else None
