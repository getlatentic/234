# SPDX-License-Identifier: AGPL-3.0-or-later
"""A personal agent for the tests: ES256 and RS256 keys made here, a JWKS of their public halves, and tokens
signed the way PACT §3.2 asks (or the ways it forbids)."""

import base64
import json
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

ISSUER = "https://pa.example"
AUDIENCE = "234-pact-test-audience"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def number(n: int) -> str:
    return b64(n.to_bytes((n.bit_length() + 7) // 8, "big"))


class Agent:
    def __init__(self) -> None:
        self.ec = ec.generate_private_key(ec.SECP256R1())
        self.rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwks(self) -> bytes:
        e = self.ec.public_key().public_numbers()
        r = self.rsa.public_key().public_numbers()
        return json.dumps({"keys": [
            {"kty": "EC", "crv": "P-256", "kid": "ec-1", "alg": "ES256",
             "x": b64(e.x.to_bytes(32, "big")), "y": b64(e.y.to_bytes(32, "big"))},
            {"kty": "RSA", "kid": "rsa-1", "alg": "RS256", "n": number(r.n), "e": number(r.e)},
        ]}).encode()  # fmt: skip

    def token(self, sub="user-1", alg="ES256", kid=None, now=None, **claims) -> str:
        at = int(time.time() if now is None else now)
        body = {"iss": ISSUER, "sub": sub, "aud": AUDIENCE, "iat": at, "exp": at + 120, **claims}
        body = {k: v for k, v in body.items() if v is not None}
        header = {"alg": alg, "kid": kid or ("ec-1" if alg == "ES256" else "rsa-1"), "typ": "JWT"}
        signing = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(body).encode())}".encode()
        if alg == "ES256":
            r, s = decode_dss_signature(self.ec.sign(signing, ec.ECDSA(hashes.SHA256())))
            signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        elif alg == "RS256":
            signature = self.rsa.sign(signing, padding.PKCS1v15(), hashes.SHA256())
        else:
            import hashlib
            import hmac

            signature = hmac.new(b"not-an-allowed-key", signing, hashlib.sha256).digest()
        return f"{signing.decode()}.{b64(signature)}"
