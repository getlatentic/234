# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ES256 verifier against signatures the `cryptography` package makes (a dev dependency: one
implementation signs, the other judges), and against everything that must fail."""

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from signatures import es256


def keypair():
    private = ec.generate_private_key(ec.SECP256R1())
    numbers = private.public_key().public_numbers()
    return private, numbers.x, numbers.y


def jws_signature(private, message: bytes) -> bytes:
    r, s = decode_dss_signature(private.sign(message, ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


@pytest.mark.parametrize("message", [b"", b"header.payload", b"x" * 5000])
def test_accepts_what_cryptography_signs(message):
    for _ in range(5):
        private, x, y = keypair()
        assert es256.verify(message, jws_signature(private, message), x, y)


def test_refuses_another_message_another_key_and_a_changed_signature():
    private, x, y = keypair()
    _, x2, y2 = keypair()
    signature = jws_signature(private, b"m")
    assert not es256.verify(b"n", signature, x, y)
    assert not es256.verify(b"m", signature, x2, y2)
    for i in (0, 31, 32, 63):
        changed = bytearray(signature)
        changed[i] ^= 1
        assert not es256.verify(b"m", bytes(changed), x, y)


def test_refuses_r_or_s_out_of_range_and_a_wrong_length():
    private, x, y = keypair()
    good = jws_signature(private, b"m")
    zero_r = bytes(32) + good[32:]
    big_s = good[:32] + es256.N.to_bytes(32, "big")
    assert not es256.verify(b"m", zero_r, x, y)
    assert not es256.verify(b"m", big_s, x, y)
    assert not es256.verify(b"m", good[:63], x, y)


def test_refuses_a_point_that_is_not_on_the_curve():
    private, x, y = keypair()
    signature = jws_signature(private, b"m")
    assert not es256.verify(b"m", signature, x, (y + 1) % es256.P)
    assert not es256.verify(b"m", signature, x + es256.P, y)


def test_the_generator_is_on_the_curve_and_has_order_n():
    assert es256.on_curve(*es256.G)
    assert es256._sum_of_multiples(es256.N, es256.G, 0, es256.G)[2] == 0


def test_the_es256_example_of_rfc_7515_appendix_a3():
    import base64

    def b64(text):
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    x = int.from_bytes(b64("f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU"), "big")
    y = int.from_bytes(b64("x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0"), "big")
    signing_input = (
        b"eyJhbGciOiJFUzI1NiJ9.eyJpc3MiOiJqb2UiLA0KICJleHAiOjEzMDA4MTkzODAsDQogImh0dHA6Ly9leGFtcGxlLmNvbS9pc19y"
        b"b290Ijp0cnVlfQ"
    )
    signature = b64("DtEhU3ljbEg8L38VWAfUAqOyKAM6-Xx-F4GawxaepmXFCgfTjDxw5djxLa8ISlSApmWQxfKTUJqPP3-Kg6NU1Q")
    assert es256.verify(signing_input, signature, x, y)
    assert not es256.verify(signing_input + b"x", signature, x, y)
