# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sealing a person's tokens at rest. A value is encrypted with a keystream of HMAC-SHA256 blocks (counter
mode) and authenticated by an HMAC over the nonce and the ciphertext, both keys derived from the Worker's
secret and a context that names whose value it is and what it is. Nothing but the standard library is used, so
the same code seals in the Worker and in a test. A value opens only under the context it was sealed for: a row
copied to another owner, or to another column, fails the check."""

import base64
import hashlib
import hmac
import secrets

VERSION = "v1"
NONCE_BYTES = 16
BLOCK = hashlib.sha256().digest_size


class SealError(Exception):
    """The value is not one this key sealed for this context."""


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SecretBox:
    def __init__(self, secret: str) -> None:
        self._master = hashlib.sha256(f"234-index-token-box\n{secret}".encode()).digest()

    def _key(self, purpose: bytes, context: str) -> bytes:
        return hmac.new(self._master, purpose + b"\0" + context.encode(), hashlib.sha256).digest()

    def _stream(self, key: bytes, nonce: bytes, length: int) -> bytes:
        blocks = (length + BLOCK - 1) // BLOCK
        return b"".join(hmac.new(key, nonce + n.to_bytes(4), hashlib.sha256).digest() for n in range(blocks))[
            :length
        ]

    def _tag(self, context: str, nonce: bytes, cipher: bytes) -> bytes:
        return hmac.new(
            self._key(b"mac", context), VERSION.encode() + nonce + cipher, hashlib.sha256
        ).digest()

    def seal(self, value: str, context: str) -> str:
        nonce, plain = secrets.token_bytes(NONCE_BYTES), value.encode()
        stream = self._stream(self._key(b"enc", context), nonce, len(plain))
        cipher = bytes(a ^ b for a, b in zip(plain, stream, strict=True))
        return ".".join(
            (VERSION, _encode(nonce), _encode(cipher), _encode(self._tag(context, nonce, cipher)))
        )

    def open(self, sealed: str, context: str) -> str:
        try:
            version, nonce_text, cipher_text, tag_text = sealed.split(".")
            nonce, cipher, tag = _decode(nonce_text), _decode(cipher_text), _decode(tag_text)
        except ValueError as error:
            raise SealError("not a sealed value") from error
        if version != VERSION or not hmac.compare_digest(tag, self._tag(context, nonce, cipher)):
            raise SealError("not sealed for this context")
        stream = self._stream(self._key(b"enc", context), nonce, len(cipher))
        return bytes(a ^ b for a, b in zip(cipher, stream, strict=True)).decode()
