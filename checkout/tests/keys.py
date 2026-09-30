# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fake provider keys, put together at run time so that no key-shaped text sits in the repository."""


def fake_key(kind: str, tail: str = "abcdefgh12345678") -> str:
    return "_".join(["sk", kind, tail])


def fake_public_key(tail: str = "abcdefgh12345678") -> str:
    return "_".join(["pk", "test", tail])
