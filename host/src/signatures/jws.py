# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compact JWS: made with an RSA key, read into its parts, and checked against a JWKS key (RS256 or ES256)."""

import base64
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import es256, rs256

if TYPE_CHECKING:
    from .ec_key import EcPrivateKey
    from .jwks import Key
    from .rsa_key import PrivateKey

MAX_TOKEN_BYTES = 8 * 1024


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _compact(value: dict[str, Any], sort: bool = False) -> str:
    return b64(json.dumps(value, separators=(",", ":"), sort_keys=sort).encode())


def encode(claims: dict[str, Any], key: PrivateKey | EcPrivateKey, typ: str = "JWT") -> str:
    """A compact JWS of the claims, as JSON with sorted keys, signed in the key's algorithm under its kid."""
    head = _compact({"alg": key.alg, "kid": key.kid, "typ": typ})
    body = _compact(claims, sort=True)
    return f"{head}.{body}.{b64(key.sign(f'{head}.{body}'.encode()))}"


@dataclass(frozen=True)
class Parts:
    header: dict[str, Any]
    claims: dict[str, Any]
    signed: bytes
    signature: bytes


def parts(token: str) -> Parts | None:
    """The header, the claims (both JSON objects) and the signature of a compact JWS, or None."""
    pieces = token.split(".")
    if len(token) > MAX_TOKEN_BYTES or len(pieces) != 3:
        return None
    try:
        header, claims = json.loads(unb64(pieces[0])), json.loads(unb64(pieces[1]))
        signature = unb64(pieces[2])
    except ValueError:
        return None
    if not isinstance(header, dict) or not isinstance(claims, dict):
        return None
    return Parts(header, claims, f"{pieces[0]}.{pieces[1]}".encode(), signature)


def signed_by(found: Parts, key: Key) -> bool:
    """Whether the key made the signature, in the algorithm the header names and the key is for."""
    if found.header.get("alg") != key.alg:
        return False
    if key.alg == "ES256":
        return es256.verify(found.signed, found.signature, key.a, key.b)
    return rs256.verify(found.signed, found.signature, key.a, key.b)
