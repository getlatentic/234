# SPDX-License-Identifier: AGPL-3.0-or-later
"""An RSA private key read from a JWK, signing RS256 by the Chinese remainder theorem. Each signature is
checked against the public key before it leaves, so a fault never publishes a signature that could leak the
key."""

import json
from dataclasses import dataclass
from typing import Any

from . import rs256
from .jws import b64, unb64

ALG = "RS256"


class BadKey(ValueError):
    """Not a consistent RSA private JWK of at least 2048 bits, with a kid."""


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
    alg: str = ALG

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
            "n": b64(self.n.to_bytes(self.size, "big")),
            "e": b64(self.e.to_bytes(size_e, "big")),
        }

    def sign(self, message: bytes) -> bytes:
        block = int.from_bytes(rs256.padded(message, self.size), "big")
        m1, m2 = pow(block, self.dp, self.p), pow(block, self.dq, self.q)
        signature = (m2 + (self.qi * (m1 - m2) % self.p) * self.q).to_bytes(self.size, "big")
        if not rs256.verify(message, signature, self.n, self.e):
            raise RuntimeError("The RSA key gave a signature its public key does not verify.")
        return signature


def _number(entry: dict[str, Any], name: str) -> int:
    return int.from_bytes(unb64(entry[name]), "big")


def from_jwk(text: str) -> PrivateKey:
    try:
        entry = json.loads(text)
        if entry.get("kty") != "RSA":
            raise BadKey("not an RSA key")
        found = PrivateKey(
            str(entry["kid"]), *(_number(entry, name) for name in ("n", "e", "p", "q", "dp", "dq", "qi"))
        )
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise BadKey("an RSA private JWK with a kid") from error
    if found.p * found.q != found.n or found.n.bit_length() < rs256.MIN_MODULUS_BITS:
        raise BadKey("a consistent RSA key of at least 2048 bits")
    return found
