# SPDX-License-Identifier: AGPL-3.0-or-later
"""Firebase ID tokens made in tests: locally generated RSA keys (the `cryptography` package, a dev dependency
only) and a key cache that serves their public halves the way Google's document does."""

import base64
import json
import time
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from accounts.keys import GoogleKeys

PROJECT = "demo-twothreefour"
NOW = 1_790_000_000.0


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64_int(number: int) -> str:
    return b64(number.to_bytes((number.bit_length() + 7) // 8, "big"))


@dataclass
class SigningKey:
    kid: str
    private: rsa.RSAPrivateKey

    @classmethod
    def generate(cls, kid: str, bits: int = 2048) -> SigningKey:
        return cls(kid, rsa.generate_private_key(public_exponent=65537, key_size=bits))

    def jwk(self) -> dict:
        numbers = self.private.public_key().public_numbers()
        return {
            "kty": "RSA",
            "alg": "RS256",
            "use": "sig",
            "kid": self.kid,
            "n": b64_int(numbers.n),
            "e": b64_int(numbers.e),
        }


def claims(**changes) -> dict:
    base = {
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": PROJECT,
        "auth_time": NOW - 30,
        "iat": NOW - 30,
        "exp": NOW + 3570,
        "sub": "uid-abc",
        "email": "Ada@Example.com",
        "email_verified": True,
        "firebase": {"sign_in_provider": "google.com", "identities": {"google.com": ["1"]}},
    }
    base.update(changes)
    return {k: v for k, v in base.items() if v is not None}


def token(
    key: SigningKey | None, payload: dict, header: dict | None = None, signature: str | None = None
) -> str:
    head = header if header is not None else {"alg": "RS256", "typ": "JWT", "kid": key.kid if key else "none"}
    signing_input = f"{b64(json.dumps(head).encode())}.{b64(json.dumps(payload).encode())}"
    if signature is None:
        signature = (
            b64(key.private.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())) if key else ""
        )
    return f"{signing_input}.{signature}"


class Google:
    """A stand-in for Google's key document: serves the keys it is given, counts the requests."""

    def __init__(self, *keys: SigningKey, cache_control: str = "public, max-age=21600") -> None:
        self.keys = list(keys)
        self.cache_control = cache_control
        self.requests = 0
        self.clock = NOW

    def fetch(self, url: str) -> tuple[int, dict[str, str], bytes]:
        self.requests += 1
        body = json.dumps({"keys": [k.jwk() for k in self.keys]}).encode()
        return 200, {"Cache-Control": self.cache_control, "Content-Type": "application/json"}, body

    def cache(self) -> GoogleKeys:
        return GoogleKeys(self.fetch, clock=lambda: self.clock)


def wall_clock() -> float:
    return time.time()
