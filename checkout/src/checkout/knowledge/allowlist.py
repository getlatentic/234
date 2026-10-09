# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hosts a source or an answer may link to: Nigeria's government domains and a short list of named
others. A look-alike (`gov.ng.evil.com`, `evilgov.ng`, a name with a login in front of it) is not allowed."""

from urllib.parse import urlsplit

GOVERNMENT_SUFFIX = ".gov.ng"
NAMED_HOSTS = frozenset({"cbn.gov.ng", "nimc.gov.ng", "jamb.gov.ng", "nysc.gov.ng", "inecnigeria.org"})


def allowed_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return host in NAMED_HOSTS or (host.endswith(GOVERNMENT_SUFFIX) and len(host) > len(GOVERNMENT_SUFFIX))


def check_domain(url: str) -> bool:
    """True for an https link whose host is on the list and which carries no credentials."""
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
        _ = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or not host or parts.username is not None or parts.password is not None:
        return False
    return allowed_host(host) and host.isascii()
