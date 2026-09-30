# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verifies a Firebase ID token completely, in this process.

What is checked, in this order, and what is not (docs/auth.md has the threat model):

- size, three dot-separated base64url parts, a JSON header and payload;
- the algorithm is RS256 and nothing else (`none`, `HS256` and the rest are refused before any key is looked
  at), and the `kid` names one of Google's current keys; the signature verifies against that key;
- `iss` is https://securetoken.google.com/<project> and `aud` is the project id;
- `exp`, `iat` and `auth_time` against the clock, with a small skew, and a life no longer than Firebase's
  hour;
- `sub` is a non-empty string, the email is present and `email_verified` is true, and the sign-in provider
  is google.com (`firebase.sign_in_provider`).

The Firebase Auth emulator signs nothing: its tokens have `alg: none`. With `emulator=True` (only ever given
when an explicit emulator host is configured, which settings refuse outside development) a token with
`alg: none` is accepted and every claim above is still checked; a signed token is verified as usual.
"""

import base64
import json
from dataclasses import dataclass
from typing import Any

from . import rs256
from .keys import GoogleKeys

MAX_TOKEN_CHARS = 8192
SKEW_SECONDS = 60
MAX_LIFE_SECONDS = 3600 + SKEW_SECONDS
PROVIDER = "google.com"


class InvalidToken(Exception):
    """The token is not acceptable. The reason is for the log, never for the caller."""


@dataclass(frozen=True)
class Identity:
    uid: str
    email: str


def _decode(part: str) -> dict[str, Any]:
    try:
        parsed = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except ValueError as error:
        raise InvalidToken("a part is not base64url JSON") from error
    if not isinstance(parsed, dict):
        raise InvalidToken("a part is not a JSON object")
    return parsed


def _check_signature(header: dict[str, Any], signing_input: bytes, signature: str, keys: GoogleKeys) -> None:
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise InvalidToken("no kid")
    key = keys.get(kid)
    if key is None:
        raise InvalidToken("unknown kid")
    try:
        raw = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
    except ValueError as error:
        raise InvalidToken("signature is not base64url") from error
    if not rs256.verify(signing_input, raw, *key):
        raise InvalidToken("bad signature")


def _number(claims: dict[str, Any], name: str) -> float:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidToken(f"{name} is not a number")
    return value


def _check_claims(claims: dict[str, Any], project: str, now: float) -> Identity:
    if claims.get("iss") != f"https://securetoken.google.com/{project}":
        raise InvalidToken("wrong iss")
    if claims.get("aud") != project:
        raise InvalidToken("wrong aud")
    exp, iat, auth_time = _number(claims, "exp"), _number(claims, "iat"), _number(claims, "auth_time")
    if exp < now - SKEW_SECONDS:
        raise InvalidToken("expired")
    if iat > now + SKEW_SECONDS or auth_time > now + SKEW_SECONDS:
        raise InvalidToken("issued in the future")
    if exp - iat > MAX_LIFE_SECONDS:
        raise InvalidToken("lives longer than an ID token may")
    uid, email = claims.get("sub"), claims.get("email")
    if not isinstance(uid, str) or not uid or len(uid) > 128:
        raise InvalidToken("no sub")
    if not isinstance(email, str) or not email or claims.get("email_verified") is not True:
        raise InvalidToken("no verified email")
    firebase = claims.get("firebase")
    if not isinstance(firebase, dict) or firebase.get("sign_in_provider") != PROVIDER:
        raise InvalidToken("not a Google sign-in")
    return Identity(uid, email.strip().lower())


def verify_id_token(
    token: object, *, project: str, keys: GoogleKeys, now: float, emulator: bool = False
) -> Identity:
    if not isinstance(token, str) or not 0 < len(token) <= MAX_TOKEN_CHARS or not project:
        raise InvalidToken("not a token")
    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidToken("not three parts")
    header = _decode(parts[0])
    algorithm = header.get("alg")
    if algorithm == "none" and emulator:
        if parts[2]:
            raise InvalidToken("an unsigned token carries a signature")
    elif algorithm == "RS256":
        _check_signature(header, f"{parts[0]}.{parts[1]}".encode(), parts[2], keys)
    else:
        raise InvalidToken(f"algorithm {algorithm!r} is not accepted")
    return _check_claims(_decode(parts[1]), project, now)
