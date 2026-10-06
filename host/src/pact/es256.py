# SPDX-License-Identifier: AGPL-3.0-or-later
"""ES256 (ECDSA on P-256 with SHA-256) verification with integers and `hashlib` alone, for the same reason as
accounts/rs256.py: the `cryptography` package does not fit the host's startup snapshot.

Only public values are involved (the key, the message, the signature), so the arithmetic need not run in
constant time. The point is checked to be on the curve before it is used; r and s are checked to be in range.
Curve: NIST P-256 (FIPS 186-4, SEC 2 secp256r1). A JWS signature is r and s, 32 bytes each, big-endian.
"""

import hashlib

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
G = (
    0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
    0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5,
)

Jacobian = tuple[int, int, int]
INFINITY: Jacobian = (1, 1, 0)


def on_curve(x: int, y: int) -> bool:
    return 0 <= x < P and 0 <= y < P and (y * y - (x * x * x + A * x + B)) % P == 0


def _double(p: Jacobian) -> Jacobian:
    x, y, z = p
    if z == 0 or y == 0:
        return INFINITY
    yy = y * y % P
    s = 4 * x * yy % P
    zz = z * z % P
    m = 3 * (x - zz) * (x + zz) % P
    x3 = (m * m - 2 * s) % P
    return x3, (m * (s - x3) - 8 * yy * yy) % P, 2 * y * z % P


def _add(p: Jacobian, q: Jacobian) -> Jacobian:
    if p[2] == 0:
        return q
    if q[2] == 0:
        return p
    z1z1, z2z2 = p[2] * p[2] % P, q[2] * q[2] % P
    u1, u2 = p[0] * z2z2 % P, q[0] * z1z1 % P
    s1, s2 = p[1] * q[2] * z2z2 % P, q[1] * p[2] * z1z1 % P
    if u1 == u2:
        return _double(p) if s1 == s2 else INFINITY
    h, r = (u2 - u1) % P, (s2 - s1) % P
    hh = h * h % P
    hhh = h * hh % P
    v = u1 * hh % P
    x3 = (r * r - hhh - 2 * v) % P
    return x3, (r * (v - x3) - s1 * hhh) % P, h * p[2] * q[2] % P


def _sum_of_multiples(k1: int, p1: tuple[int, int], k2: int, p2: tuple[int, int]) -> Jacobian:
    """k1·P1 + k2·P2 in one pass over the bits (Shamir's trick)."""
    a, b = (*p1, 1), (*p2, 1)
    both = _add(a, b)
    result = INFINITY
    for i in range(max(k1.bit_length(), k2.bit_length()) - 1, -1, -1):
        result = _double(result)
        bit1, bit2 = (k1 >> i) & 1, (k2 >> i) & 1
        if bit1 and bit2:
            result = _add(result, both)
        elif bit1:
            result = _add(result, a)
        elif bit2:
            result = _add(result, b)
    return result


def verify(message: bytes, signature: bytes, x: int, y: int) -> bool:
    if len(signature) != 64 or not on_curve(x, y):
        return False
    r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    if not (1 <= r < N and 1 <= s < N):
        return False
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, -1, N)
    point = _sum_of_multiples(e * w % N, G, r * w % N, (x, y))
    if point[2] == 0:
        return False
    zinv = pow(point[2], -1, P)
    return point[0] * zinv * zinv % P % N == r
