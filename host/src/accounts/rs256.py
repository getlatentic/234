# SPDX-License-Identifier: AGPL-3.0-or-later
"""RS256 (RSASSA-PKCS1-v1_5 with SHA-256) verification with nothing but `pow` and `hashlib`.

The host runs on Pyodide, where the `cryptography` package would add tens of megabytes to the startup
snapshot. Verifying needs one modular exponentiation: the signature raised to the public exponent must equal
the padded digest. The padded block is rebuilt and compared whole, so a signature with garbage in its padding
(the forgeries that parse a block instead of building one) is refused.
"""

import hashlib
import hmac

SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")
MIN_MODULUS_BITS = 2048
MAX_EXPONENT_BITS = 64


def verify(message: bytes, signature: bytes, modulus: int, exponent: int) -> bool:
    if (
        modulus.bit_length() < MIN_MODULUS_BITS
        or not 3 <= exponent < 1 << MAX_EXPONENT_BITS
        or exponent % 2 == 0
    ):
        return False
    size = (modulus.bit_length() + 7) // 8
    if len(signature) != size:
        return False
    number = int.from_bytes(signature, "big")
    if number >= modulus:
        return False
    block = pow(number, exponent, modulus).to_bytes(size, "big")
    tail = SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    expected = b"\x00\x01" + b"\xff" * (size - len(tail) - 3) + b"\x00" + tail
    return hmac.compare_digest(block, expected)
