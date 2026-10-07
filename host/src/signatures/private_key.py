# SPDX-License-Identifier: AGPL-3.0-or-later
"""A private JWK read as the key its `kty` names: RSA (RS256) or P-256 (ES256)."""

import json

from . import ec_key, rsa_key
from .rsa_key import BadKey


def from_jwk(text: str) -> rsa_key.PrivateKey | ec_key.EcPrivateKey:
    try:
        kty = json.loads(text).get("kty")
    except (ValueError, AttributeError) as error:
        raise BadKey("a private JWK") from error
    return ec_key.from_jwk(text) if kty == "EC" else rsa_key.from_jwk(text)
