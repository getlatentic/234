# SPDX-License-Identifier: AGPL-3.0-or-later
"""AWS Signature Version 4 for one POST or GET with a body: the headers that make an IAM-authenticated
request. Only what the search gateway needs (docs/web.md): no query string, no chunked bodies, no session
token."""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

ALGORITHM = "AWS4-HMAC-SHA256"


@dataclass(frozen=True)
class Credentials:
    access_key_id: str
    secret_access_key: str

    def __repr__(self) -> str:
        return f"Credentials({self.access_key_id[:4]}...)"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def _signing_key(secret: str, day: str, region: str, service: str) -> bytes:
    key = _hmac(f"AWS4{secret}".encode(), day)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    return key


def signed_headers(
    credentials: Credentials,
    method: str,
    url: str,
    body: bytes,
    region: str,
    service: str,
    now: datetime | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """`extra` headers are signed too (lower-case names). Returns every header to send: `extra`, `host`,
    `x-amz-date` and `authorization`."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    stamp, day = moment.strftime("%Y%m%dT%H%M%SZ"), moment.strftime("%Y%m%d")
    parts = urlsplit(url)
    headers = {**(extra or {}), "host": parts.netloc, "x-amz-date": stamp}
    names = sorted(headers)
    canonical_headers = "".join(f"{n}:{' '.join(headers[n].split())}\n" for n in names)
    listed = ";".join(names)
    canonical = "\n".join([method, parts.path or "/", parts.query, canonical_headers, listed, _sha256(body)])
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join([ALGORITHM, stamp, scope, _sha256(canonical.encode())])
    signature = hmac.new(
        _signing_key(credentials.secret_access_key, day, region, service), to_sign.encode(), hashlib.sha256
    ).hexdigest()
    headers["authorization"] = (
        f"{ALGORITHM} Credential={credentials.access_key_id}/{scope}, SignedHeaders={listed}, "
        f"Signature={signature}"
    )
    return headers
