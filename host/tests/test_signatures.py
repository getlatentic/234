# SPDX-License-Identifier: AGPL-3.0-or-later
"""RS256 signing with an RSA JWK, and compact JWS read back: what the host signs verifies with `cryptography`,
and a token altered in any part does not verify."""

import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from signatures import jws
from signatures.jwks import Key
from signatures.rsa_key import BadKey, from_jwk

from .pact_support import host_signing_key, unb64


@pytest.fixture(scope="module")
def key():
    return from_jwk(host_signing_key())


def test_a_token_the_key_signs_verifies_with_an_independent_library(key):
    token = jws.encode({"sub": "s", "n": 1}, key)
    head, body, signature = token.split(".")
    public = key.public()
    numbers = rsa.RSAPublicNumbers(
        int.from_bytes(unb64(public["e"]), "big"), int.from_bytes(unb64(public["n"]), "big")
    )
    numbers.public_key().verify(
        unb64(signature), f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    assert json.loads(unb64(head)) == {"alg": "RS256", "kid": "host-test", "typ": "JWT"}


def test_a_token_altered_anywhere_does_not_verify(key):
    token = jws.encode({"sub": "s"}, key)
    mine = Key("RS256", key.n, key.e)
    assert jws.signed_by(jws.parts(token), mine)
    head, body, signature = token.split(".")
    other_body = jws.b64(json.dumps({"sub": "t"}).encode())
    for changed in (f"{head}.{other_body}.{signature}", f"{head}.{body}.{signature[:-4]}AAAA"):
        assert not jws.signed_by(jws.parts(changed), mine)
    assert not jws.signed_by(jws.parts(token), Key("ES256", 1, 2)), "the header's alg must be the key's"
    assert jws.parts("a.b") is None and jws.parts("x" * 9000) is None


def test_a_key_that_is_not_a_consistent_rsa_jwk_is_refused(key):
    entry = json.loads(host_signing_key())
    for broken in (
        {**entry, "kty": "EC"},
        {k: v for k, v in entry.items() if k != "kid"},
        {**entry, "p": entry["q"]},
    ):
        with pytest.raises(BadKey):
            from_jwk(json.dumps(broken))


RFC_6979_D = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721


def test_es256_signing_matches_rfc_6979s_own_test_vector():
    import hashlib

    from signatures.ec_key import EcPrivateKey, _affine, _ladder, nonce
    from signatures.es256 import G

    digest = hashlib.sha256(b"sample").digest()
    assert nonce(RFC_6979_D, digest) == 0xA6E3C57DD01ABE90086538398355DD4C3B17AA873382B0F24D6129493D8AAD60
    x, y = _affine(_ladder(RFC_6979_D, G))
    signature = EcPrivateKey("t", RFC_6979_D, x, y).sign(b"sample")
    assert signature.hex().upper() == (
        "EFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716"
        "F7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8"
    )


def test_an_es256_token_verifies_with_an_independent_library_and_a_bad_key_is_refused():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    from signatures.private_key import from_jwk as private_key

    from .reach_support import agent_key_pair

    text, public = agent_key_pair()
    key = private_key(text)
    head, body, signature = jws.encode({"sub": "s"}, key).split(".")
    raw = unb64(signature)
    numbers = ec.EllipticCurvePublicNumbers(
        int.from_bytes(unb64(public["x"]), "big"), int.from_bytes(unb64(public["y"]), "big"), ec.SECP256R1()
    )
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    numbers.public_key().verify(der, f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
    entry = json.loads(text)
    for broken in ({**entry, "crv": "P-384"}, {**entry, "d": entry["x"]}):
        with pytest.raises(BadKey):
            private_key(json.dumps(broken))
