# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bachs' webhook signature (https://docs.bachs.io/guides/webhooks/overview): `X-Bachs-Signature-V2` is
`t=<unix seconds>,v1=<hex>`, the hex being HMAC-SHA256 of `{t}.{raw body}` with the endpoint's secret. While a
secret is rotated, Bachs signs with both and sends one `v1` for each, so any `v1` that matches is enough.

A delivery older than five minutes is refused as a replay, and one dated ahead of this clock by more than a
small skew is refused too: the timestamp is inside what was signed, so only Bachs could have set it."""

import hashlib
import hmac
from enum import StrEnum

SIGNATURE_HEADER = "x-bachs-signature-v2"
TOLERANCE_SECONDS = 300
FUTURE_SKEW_SECONDS = 30


class Verdict(StrEnum):
    GENUINE = "genuine"
    UNSIGNED = "unsigned"
    STALE = "stale"
    FUTURE = "future"


def sign(secret: str, timestamp: int, raw: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256).hexdigest()


def header_for(secrets: tuple[str, ...], timestamp: int, raw: bytes) -> str:
    """The header Bachs sends, signed with each secret: what the simulator and the tests send."""
    return ",".join([f"t={timestamp}", *(f"v1={sign(s, timestamp, raw)}" for s in secrets)])


def parse(header: str) -> tuple[int | None, list[str]]:
    """The timestamp and every `v1` signature in the header; parts it does not know are left out."""
    timestamp: int | None = None
    signatures: list[str] = []
    for part in header.split(","):
        name, _, value = part.strip().partition("=")
        if name == "t" and value.isdecimal() and value.isascii():
            timestamp = int(value)
        elif name == "v1" and value:
            signatures.append(value)
    return timestamp, signatures


def _matches(expected: list[str], given: list[str]) -> bool:
    found = False
    for want in expected:
        for got in given:
            found |= hmac.compare_digest(want.encode(), got.encode())
    return found


def check(raw: bytes, header: str, secrets: tuple[str, ...], now_ms: int) -> Verdict:
    timestamp, given = parse(header)
    if timestamp is None or not given:
        return Verdict.UNSIGNED
    if not _matches([sign(s, timestamp, raw) for s in secrets], given):
        return Verdict.UNSIGNED
    age = now_ms // 1000 - timestamp
    if age > TOLERANCE_SECONDS:
        return Verdict.STALE
    if age < -FUTURE_SKEW_SECONDS:
        return Verdict.FUTURE
    return Verdict.GENUINE
