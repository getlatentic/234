# SPDX-License-Identifier: AGPL-3.0-or-later
"""The verification of a Firebase ID token, with RSA keys generated here and signed by a real library, so a
token made by one implementation is judged by the other."""

import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from accounts import rs256
from accounts.firebase_token import InvalidToken, verify_id_token

from .firebase_support import NOW, PROJECT, Google, SigningKey, b64, claims, token


@pytest.fixture(scope="module")
def key() -> SigningKey:
    return SigningKey.generate("key-1")


@pytest.fixture(scope="module")
def other() -> SigningKey:
    return SigningKey.generate("key-1")  # the same kid, another key: a forged signature


@pytest.fixture
def google(key) -> Google:
    return Google(key)


def verify(google, text, **options):
    return verify_id_token(text, project=PROJECT, keys=google.cache(), now=NOW, **options)


def refused(google, text, why, **options):
    with pytest.raises(InvalidToken, match=why):
        verify(google, text, **options)


def test_a_valid_token_gives_the_uid_and_the_email_in_lower_case(google, key):
    identity = verify(google, token(key, claims()))
    assert (identity.uid, identity.email) == ("uid-abc", "ada@example.com")


def test_the_wrong_audience_is_refused(google, key):
    refused(google, token(key, claims(aud="another-project")), "aud")


def test_the_wrong_issuer_is_refused(google, key):
    refused(google, token(key, claims(iss="https://securetoken.google.com/another-project")), "iss")
    refused(google, token(key, claims(iss=f"https://accounts.google.com/{PROJECT}")), "iss")


def test_an_expired_token_is_refused_beyond_the_skew_and_accepted_inside_it(google, key):
    refused(google, token(key, claims(exp=NOW - 61, iat=NOW - 3661, auth_time=NOW - 3661)), "expired")
    assert verify(google, token(key, claims(exp=NOW - 30, iat=NOW - 3630, auth_time=NOW - 3630)))


def test_a_token_not_yet_valid_is_refused_beyond_the_skew(google, key):
    refused(google, token(key, claims(iat=NOW + 61, exp=NOW + 3600)), "future")
    refused(google, token(key, claims(auth_time=NOW + 120)), "future")
    assert verify(google, token(key, claims(iat=NOW + 30, auth_time=NOW + 30, exp=NOW + 3600)))


def test_a_token_that_lives_longer_than_an_hour_is_refused(google, key):
    refused(google, token(key, claims(exp=NOW + 86400)), "longer")


def test_alg_none_is_refused_even_with_a_valid_looking_body(google, key):
    header = {"alg": "none", "typ": "JWT"}
    refused(google, token(None, claims(), header=header, signature=""), "none")
    refused(google, token(key, claims(), header=header), "none")


@pytest.mark.parametrize("alg", ["HS256", "HS384", "RS384", "RS512", "ES256", "PS256", "rs256", ""])
def test_every_algorithm_but_rs256_is_refused(google, key, alg):
    refused(google, token(key, claims(), header={"alg": alg, "kid": key.kid}), "not accepted")


def test_a_hmac_token_signed_with_the_public_key_as_the_secret_is_refused(google, key):
    header = {"alg": "HS256", "kid": key.kid}
    refused(google, token(key, claims(), header=header, signature=b64(b"x" * 32)), "not accepted")


def test_a_tampered_signature_or_payload_is_refused(google, key):
    good = token(key, claims())
    head, body, sig = good.split(".")
    flipped = sig[:-4] + ("AAAA" if not sig.endswith("AAAA") else "BBBB")
    refused(google, f"{head}.{body}.{flipped}", "signature")
    forged_body = token(key, claims(sub="someone-else")).split(".")[1]
    refused(google, f"{head}.{forged_body}.{sig}", "signature")


def test_a_signature_from_another_key_with_the_same_kid_is_refused(google, other):
    refused(google, token(other, claims()), "signature")


def test_a_short_or_padded_signature_is_refused(google, key):
    head, body, _ = token(key, claims()).split(".")
    refused(google, f"{head}.{body}.{b64(b'short')}", "signature")
    refused(google, f"{head}.{body}.", "signature")


def test_an_unknown_kid_makes_one_refetch_and_is_then_refused(google, key):
    stranger = SigningKey.generate("unknown-kid", bits=2048)
    cache = google.cache()
    with pytest.raises(InvalidToken, match="unknown kid"):
        verify_id_token(token(stranger, claims()), project=PROJECT, keys=cache, now=NOW)
    assert google.requests == 1  # the first load; the unknown kid came straight after it
    google.clock += 61
    with pytest.raises(InvalidToken, match="unknown kid"):
        verify_id_token(token(stranger, claims()), project=PROJECT, keys=cache, now=NOW)
    assert google.requests == 2  # one refetch, not two


def test_a_rotated_key_is_found_by_the_refetch(key):
    google = Google(key)
    cache = google.cache()
    verify_id_token(token(key, claims()), project=PROJECT, keys=cache, now=NOW)
    fresh = SigningKey.generate("key-2")
    google.keys.append(fresh)
    google.clock += 120
    assert verify_id_token(token(fresh, claims()), project=PROJECT, keys=cache, now=NOW)


def test_unknown_kids_cannot_turn_into_a_stream_of_requests(google, key):
    cache = google.cache()
    for n in range(20):
        with pytest.raises(InvalidToken):
            verify_id_token(
                token(key, claims(), header={"alg": "RS256", "kid": f"guess-{n}"}),
                project=PROJECT,
                keys=cache,
                now=NOW,
            )
    assert google.requests == 1


def test_a_missing_kid_is_refused(google, key):
    refused(google, token(key, claims(), header={"alg": "RS256"}), "kid")


def test_keys_are_cached_for_as_long_as_google_says(key):
    google = Google(key, cache_control="public, max-age=300, must-revalidate")
    cache = google.cache()
    for _ in range(3):
        verify_id_token(token(key, claims()), project=PROJECT, keys=cache, now=NOW)
    assert google.requests == 1
    google.clock += 299
    verify_id_token(token(key, claims()), project=PROJECT, keys=cache, now=NOW)
    assert google.requests == 1
    google.clock += 2
    verify_id_token(token(key, claims()), project=PROJECT, keys=cache, now=NOW)
    assert google.requests == 2


def test_an_unverified_email_is_refused(google, key):
    refused(google, token(key, claims(email_verified=False)), "email")
    refused(google, token(key, claims(email_verified="true")), "email")
    refused(google, token(key, claims(email_verified=None)), "email")
    refused(google, token(key, claims(email=None)), "email")


def test_any_provider_but_google_is_refused(google, key):
    for provider in ("password", "phone", "anonymous", "facebook.com"):
        refused(google, token(key, claims(firebase={"sign_in_provider": provider})), "Google")
    refused(google, token(key, claims(firebase=None)), "Google")


def test_no_sub_is_refused(google, key):
    refused(google, token(key, claims(sub="")), "sub")
    refused(google, token(key, claims(sub=None)), "sub")
    refused(google, token(key, claims(sub=12)), "sub")


def test_times_must_be_numbers(google, key):
    refused(google, token(key, claims(exp="9999999999")), "exp")
    refused(google, token(key, claims(iat=True)), "iat")
    refused(google, token(key, claims(auth_time=None)), "auth_time")


@pytest.mark.parametrize("text", ["", "a.b", "a.b.c.d", "....", "x" * 9000, None, 12, b"a.b.c", {"a": 1}])
def test_what_is_not_a_token_is_refused(google, text):
    with pytest.raises(InvalidToken):
        verify(google, text)


def test_a_well_formed_signed_token_over_the_size_limit_is_refused_before_it_is_parsed(google, key):
    refused(google, token(key, claims(padding="x" * 9000)), "not a token")


def test_without_a_project_nothing_is_accepted(google, key):
    with pytest.raises(InvalidToken):
        verify_id_token(token(key, claims()), project="", keys=google.cache(), now=NOW)


def test_the_emulator_accepts_an_unsigned_token_only_when_asked_and_still_checks_the_claims(google, key):
    unsigned = token(None, claims(), header={"alg": "none", "typ": "JWT"}, signature="")
    assert verify(google, unsigned, emulator=True).uid == "uid-abc"
    refused(google, unsigned, "none")
    bad_claims = token(None, claims(aud="x"), header={"alg": "none"}, signature="")
    refused(google, bad_claims, "aud", emulator=True)
    signed_none = token(None, claims(), header={"alg": "none"}, signature="c2ln")
    refused(google, signed_none, "unsigned", emulator=True)


def test_the_emulator_flag_does_not_weaken_signed_tokens(google, key, other):
    assert verify(google, token(key, claims()), emulator=True)
    refused(google, token(other, claims()), "signature", emulator=True)


class TestRs256:
    def test_the_padding_is_rebuilt_not_parsed(self, key):
        numbers = key.private.public_key().public_numbers()
        message = b"m"
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        signature = key.private.sign(message, padding.PKCS1v15(), hashes.SHA256())
        assert rs256.verify(message, signature, numbers.n, numbers.e)
        assert not rs256.verify(b"n", signature, numbers.n, numbers.e)

    def test_a_signature_whose_block_is_not_the_padded_digest_is_refused(self, key):
        private = key.private.private_numbers()
        message = b"m"
        size = (private.public_numbers.n.bit_length() + 7) // 8
        tail = rs256.SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
        block = b"\x00\x02" + b"\xaa" * (size - len(tail) - 3) + b"\x00" + tail
        forged = pow(int.from_bytes(block, "big"), private.d, private.public_numbers.n).to_bytes(size, "big")
        assert not rs256.verify(message, forged, private.public_numbers.n, private.public_numbers.e)

    def test_a_validly_signed_message_is_refused_under_a_key_of_fewer_than_2048_bits(self):
        small = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        signature = small.sign(b"m", padding.PKCS1v15(), hashes.SHA256())
        numbers = small.public_key().public_numbers()
        assert not rs256.verify(b"m", signature, numbers.n, numbers.e)

    def test_small_keys_and_odd_exponents_are_refused(self):
        small = rsa.generate_private_key(public_exponent=65537, key_size=1024).public_key().public_numbers()
        assert not rs256.verify(b"m", b"\x00" * 128, small.n, small.e)
        big = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key().public_numbers()
        assert not rs256.verify(b"m", b"\x00" * 256, big.n, 2)
        assert not rs256.verify(b"m", b"\x00" * 256, big.n, 1)
