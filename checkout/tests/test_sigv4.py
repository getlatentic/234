# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signature Version 4 (web/sigv4.py) against AWS's published test case `get-vanilla`: the same request must
give the same signature, byte for byte."""

from datetime import UTC, datetime

from checkout.web.sigv4 import Credentials, signed_headers

CREDENTIALS = Credentials("AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY")
MOMENT = datetime(2015, 8, 30, 12, 36, 0, tzinfo=UTC)
SIGNATURE = "5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"


def test_the_published_get_vanilla_request_has_the_published_signature():
    headers = signed_headers(
        CREDENTIALS, "GET", "https://example.amazonaws.com/", b"", "us-east-1", "service", MOMENT
    )
    assert headers["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
        f"SignedHeaders=host;x-amz-date, Signature={SIGNATURE}"
    )
    assert headers["host"] == "example.amazonaws.com" and headers["x-amz-date"] == "20150830T123600Z"


def test_the_body_and_a_signed_header_change_the_signature():
    base = signed_headers(CREDENTIALS, "POST", "https://h.example.com/mcp", b"{}", "us-east-1", "s", MOMENT)
    other_body = signed_headers(
        CREDENTIALS, "POST", "https://h.example.com/mcp", b"{ }", "us-east-1", "s", MOMENT
    )
    extra = signed_headers(
        CREDENTIALS,
        "POST",
        "https://h.example.com/mcp",
        b"{}",
        "us-east-1",
        "s",
        MOMENT,
        {"accept": "application/json"},
    )
    signatures = {h["authorization"].rsplit("=", 1)[1] for h in (base, other_body, extra)}
    assert len(signatures) == 3 and "accept" in extra["authorization"]


def test_the_secret_never_appears_in_a_header_or_the_repr():
    headers = signed_headers(
        CREDENTIALS, "GET", "https://example.amazonaws.com/", b"", "us-east-1", "s", MOMENT
    )
    assert CREDENTIALS.secret_access_key not in " ".join(headers.values()) + repr(CREDENTIALS)
