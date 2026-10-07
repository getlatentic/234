# SPDX-License-Identifier: AGPL-3.0-or-later
"""The host's own key for PACT Delegated (§5.4, §5.6): it signs delegation tokens and receipts with RS256,
and its public half is the JWKS the authorization server metadata names. PACT_SIGNING_KEY holds the private
key as an RSA JWK (tools/pact-key.mjs makes one). Signing is a modular exponentiation by the Chinese
remainder theorem, checked against the public key before the signature leaves, so a fault never publishes
a signature that could leak the key."""

import base64
import json
from dataclasses import dataclass
from functools import cache
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from accounts import rs256

ALG = "RS256"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _number(entry: dict[str, Any], name: str) -> int:
    return int.from_bytes(_unb64(entry[name]), "big")


@dataclass(frozen=True)
class PrivateKey:
    kid: str
    n: int
    e: int
    p: int
    q: int
    dp: int
    dq: int
    qi: int

    @property
    def size(self) -> int:
        return (self.n.bit_length() + 7) // 8

    def public(self) -> dict[str, str]:
        size_e = (self.e.bit_length() + 7) // 8
        return {
            "kty": "RSA",
            "kid": self.kid,
            "use": "sig",
            "alg": ALG,
            "n": _b64(self.n.to_bytes(self.size, "big")),
            "e": _b64(self.e.to_bytes(size_e, "big")),
        }

    def sign(self, message: bytes) -> bytes:
        block = int.from_bytes(rs256.padded(message, self.size), "big")
        m1, m2 = pow(block, self.dp, self.p), pow(block, self.dq, self.q)
        signature = (m2 + (self.qi * (m1 - m2) % self.p) * self.q).to_bytes(self.size, "big")
        if not rs256.verify(message, signature, self.n, self.e):
            raise RuntimeError("The PACT signing key gave a signature its public key does not verify.")
        return signature


def enabled() -> bool:
    return bool(settings.PACT_SIGNING_KEY)


@cache
def key() -> PrivateKey:
    try:
        entry = json.loads(settings.PACT_SIGNING_KEY)
        if entry.get("kty") != "RSA":
            raise ValueError("not an RSA key")
        found = PrivateKey(
            str(entry["kid"]), *(_number(entry, name) for name in ("n", "e", "p", "q", "dp", "dq", "qi"))
        )
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ImproperlyConfigured("PACT_SIGNING_KEY is an RSA private JWK with a kid.") from error
    if found.p * found.q != found.n or found.n.bit_length() < rs256.MIN_MODULUS_BITS:
        raise ImproperlyConfigured("PACT_SIGNING_KEY is not a consistent RSA key of at least 2048 bits.")
    return found


def jwks() -> dict[str, list[dict[str, str]]]:
    return {"keys": [key().public()]}


def sign(claims: dict[str, Any]) -> str:
    """A compact JWS of the claims, as JSON with sorted keys."""
    found = key()
    header = _b64(json.dumps({"alg": ALG, "kid": found.kid, "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    signed = f"{header}.{body}".encode()
    return f"{header}.{body}.{_b64(found.sign(signed))}"


def verified(token: str) -> dict[str, Any] | None:
    """The claims of a JWS this host signed, or None for anything else."""
    parts = token.split(".")
    if len(token) > 8 * 1024 or len(parts) != 3:
        return None
    try:
        header, claims, signature = (
            json.loads(_unb64(parts[0])),
            json.loads(_unb64(parts[1])),
            _unb64(parts[2]),
        )
    except ValueError:
        return None
    found = key()
    if not isinstance(header, dict) or header.get("alg") != ALG or header.get("kid") != found.kid:
        return None
    if not rs256.verify(f"{parts[0]}.{parts[1]}".encode(), signature, found.n, found.e):
        return None
    return claims if isinstance(claims, dict) else None
