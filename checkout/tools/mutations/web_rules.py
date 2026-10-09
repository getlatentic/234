# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the web tool will and will not fetch (checkout web/): only public https names, every redirect
checked, robots.txt honoured, a size and a redirect limit, the deny list and the switch, and quoted text."""

from tools.mutations.model import Mutation

WEB = ["tests/test_web.py"]


def checkout(name: str, path: str, old: str, new: str) -> Mutation:
    return Mutation(name, path, old, new, WEB)


MUTATIONS: list[Mutation] = [
    checkout(
        "web: only https is read",
        "src/checkout/web/safe_url.py",
        'if parts.scheme != "https":',
        "if False:",
    ),
    checkout(
        "web: no login in an address",
        "src/checkout/web/safe_url.py",
        "if not host or parts.username is not None or parts.password is not None:",
        "if not host:",
    ),
    checkout(
        "web: only the standard port",
        "src/checkout/web/safe_url.py",
        "if port not in (None, 443):",
        "if False:",
    ),
    checkout(
        "web: a numeric host is not a public name",
        "src/checkout/web/safe_url.py",
        "if _NUMERIC.match(host) or labels[-1].isdigit() or host.endswith(PRIVATE_SUFFIXES):",
        "if host.endswith(PRIVATE_SUFFIXES):",
    ),
    checkout(
        "web: a private suffix is not a public name",
        "src/checkout/web/safe_url.py",
        "or host.endswith(PRIVATE_SUFFIXES):",
        "or False:",
    ),
    checkout(
        "web: a name needs two labels",
        "src/checkout/web/safe_url.py",
        "len(labels) < 2 or ",
        "",
    ),
    checkout(
        "web: a redirect is checked again",
        "src/checkout/web/reader.py",
        "            self._allowed(current)\n            if check_robots:",
        "            if check_robots:",
    ),
    checkout(
        "web: redirects are limited",
        "src/checkout/web/reader.py",
        "for _ in range(MAX_REDIRECTS + 1):",
        "for _ in range(50):",
    ),
    checkout(
        "web: robots.txt is honoured",
        "src/checkout/web/reader.py",
        "if not robots.allows(entry.status, entry.text, url):",
        "if False:",
    ),
    checkout(
        "web: a site whose robots.txt fails is not read",
        "src/checkout/web/robots.py",
        "if status is None or status >= 500:",
        "if status is None:",
    ),
    checkout(
        "web: the deny list refuses a site",
        "src/checkout/web/reader.py",
        'if safe_url.under(urlsplit(url).hostname or "", self._policy.deny):',
        "if False:",
    ),
    checkout(
        "web: the switch turns the tool off",
        "src/checkout/web/reader.py",
        "if not self._policy.enabled:",
        "if False:",
    ),
    checkout(
        "web: a page over 2 MB is refused",
        "src/checkout/web/reader.py",
        "if got.too_large:",
        "if False:",
    ),
    checkout(
        "web: only pages and plain text are read",
        "src/checkout/web/reader.py",
        "if base not in TEXT_TYPES:",
        "if False:",
    ),
    checkout(
        "web: a page is cut at its limit",
        "src/checkout/web/reader.py",
        "text[:MAX_CHARS], len(text) > MAX_CHARS",
        "text, False",
    ),
    checkout(
        "web: a page is kept for an hour",
        "src/checkout/web/cache.py",
        "TTL_MS = 3_600_000",
        "TTL_MS = 0",
    ),
    checkout(
        "web: scripts and menus are left out",
        "src/checkout/web/extract.py",
        'SKIPPED = frozenset({"script", "style", "noscript",',
        'SKIPPED = frozenset({"style", "noscript",',
    ),
    checkout(
        "web: a page's text is quoted line by line",
        "src/checkout/connectors/web.py",
        "{quoted(page.text) or '> (no text)'}",
        "{page.text or '> (no text)'}",
    ),
]
