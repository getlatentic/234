# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which redirect URIs a client may register: HTTPS, or HTTP on the loopback (MCP authorization, communication
security). No fragment, no user information, at most 2000 characters."""

from urllib.parse import urlsplit

LOOPBACK = {"localhost", "127.0.0.1", "[::1]", "::1"}
MAX_LENGTH = 2000


def is_loopback(uri: str) -> bool:
    return (urlsplit(uri).hostname or "") in LOOPBACK


def acceptable(uri: object) -> bool:
    if not isinstance(uri, str) or not uri or len(uri) > MAX_LENGTH:
        return False
    try:
        parts = urlsplit(uri)
        parts.port  # noqa: B018 - raises ValueError for a port that is not a number
    except ValueError:
        return False
    if parts.fragment or "@" in parts.netloc or not parts.hostname:
        return False
    return parts.scheme == "https" or (parts.scheme == "http" and is_loopback(uri))


def matches(registered: list[str], given: str) -> bool:
    """Exact match, except that a loopback URI may name any port (RFC 8252 section 7.3)."""
    if given in registered:
        return True
    if not is_loopback(given):
        return False
    asked = urlsplit(given)
    return any(
        is_loopback(r)
        and (p := urlsplit(r)).scheme == asked.scheme
        and p.hostname == asked.hostname
        and p.path == asked.path
        and p.query == asked.query
        for r in registered
    )
