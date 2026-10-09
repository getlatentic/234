# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which addresses the web tool may fetch: public https pages by name. No IP address in any spelling, no
credentials, no other port, no name that is not a public one (`localhost`, `*.internal`, a single label)."""

import re
from urllib.parse import urlsplit

PRIVATE_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet", ".arpa")
_NUMERIC = re.compile(r"^[0-9a-fx.:\[\]]+$", re.IGNORECASE)
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def problem(url: str) -> str | None:
    """Why this address may not be fetched, or None."""
    try:
        parts = urlsplit(url.strip())
        host, port = parts.hostname, parts.port
    except ValueError:
        return "That is not a web address."
    if parts.scheme != "https":
        return "Only https addresses can be read."
    if not host or parts.username is not None or parts.password is not None:
        return "An address needs a host name and no login."
    if port not in (None, 443):
        return "Only the standard https port can be read."
    return _host_problem(host.lower().rstrip("."))


def _host_problem(host: str) -> str | None:
    labels = host.split(".")
    if not host.isascii() or len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        return "That host is not a public name."
    if _NUMERIC.match(host) or labels[-1].isdigit() or host.endswith(PRIVATE_SUFFIXES):
        return "That host is not a public name."
    return None


def under(host: str, domains: tuple[str, ...]) -> bool:
    """Whether `host` is one of `domains` or a subdomain of one."""
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith(f".{d}") for d in domains)
