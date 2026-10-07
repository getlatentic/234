# SPDX-License-Identifier: AGPL-3.0-or-later
"""An ES256 (P-256) private key read from a JWK, signing with a nonce derived from the key and the message
(RFC 6979, so no random source is trusted with it). The nonce multiplies the base point by a Montgomery ladder
over all 256 bits, one doubling and one addition per bit whatever the bit is; Python's integers are not
constant-time, so this narrows what timing tells and does not remove it. Each signature is checked against the
public key before it leaves."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from .es256 import INFINITY, G, Jacobian, N, P, _add, _double, on_curve, verify
from .jws import b64, unb64
from .rsa_key import BadKey

ALG = "ES256"
BYTES = 32


def _ladder(k: int, point: tuple[int, int]) -> Jacobian:
    low, high = INFINITY, (*point, 1)
    for i in range(255, -1, -1):
        if (k >> i) & 1:
            low, high = _add(low, high), _double(high)
        else:
            high, low = _add(low, high), _double(low)
    return low


def _affine(point: Jacobian) -> tuple[int, int]:
    zinv = pow(point[2], -1, P)
    return point[0] * zinv * zinv % P, point[1] * zinv * zinv * zinv % P


def nonce(d: int, digest: bytes) -> int:
    """RFC 6979 §3.2 for P-256 with HMAC-SHA256."""
    x, h = d.to_bytes(BYTES, "big"), (int.from_bytes(digest, "big") % N).to_bytes(BYTES, "big")
    v, k = b"\x01" * BYTES, b"\x00" * BYTES
    for marker in (b"\x00", b"\x01"):
        k = hmac.new(k, v + marker + x + h, hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        candidate = int.from_bytes(v, "big")
        if 1 <= candidate < N:
            return candidate
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


@dataclass(frozen=True)
class EcPrivateKey:
    kid: str
    d: int
    x: int
    y: int
    alg: str = ALG

    def public(self) -> dict[str, str]:
        return {
            "kty": "EC",
            "crv": "P-256",
            "kid": self.kid,
            "use": "sig",
            "alg": ALG,
            "x": b64(self.x.to_bytes(BYTES, "big")),
            "y": b64(self.y.to_bytes(BYTES, "big")),
        }

    def sign(self, message: bytes) -> bytes:
        digest = hashlib.sha256(message).digest()
        e, k = int.from_bytes(digest, "big"), nonce(self.d, digest)
        r = _affine(_ladder(k, G))[0] % N
        s = pow(k, -1, N) * (e + r * self.d) % N
        signature = r.to_bytes(BYTES, "big") + s.to_bytes(BYTES, "big")
        if r == 0 or s == 0 or not verify(message, signature, self.x, self.y):
            raise RuntimeError("The P-256 key gave a signature its public key does not verify.")
        return signature


def _number(entry: dict[str, Any], name: str) -> int:
    return int.from_bytes(unb64(entry[name]), "big")


def from_jwk(text: str) -> EcPrivateKey:
    try:
        entry = json.loads(text)
        if entry.get("kty") != "EC" or entry.get("crv") != "P-256":
            raise BadKey("not a P-256 key")
        found = EcPrivateKey(str(entry["kid"]), _number(entry, "d"), _number(entry, "x"), _number(entry, "y"))
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise BadKey("a P-256 private JWK with a kid") from error
    if not (1 <= found.d < N and on_curve(found.x, found.y)) or _affine(_ladder(found.d, G)) != (
        found.x,
        found.y,
    ):
        raise BadKey("a consistent P-256 key")
    return found
