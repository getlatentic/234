# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which Paystack Index 234 talks to (`INDEX_MODE`): the simulator, or Index itself. Index's addresses are
configuration, but only an address on its own hosts is accepted, so a person's token can go nowhere else. The
key the tokens are sealed with is a Worker secret (`INDEX_TOKEN_KEY`); the simulator may borrow one from the
approval secret, Index itself never does."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, cast
from urllib.parse import urlsplit

from ...errors import ConfigError
from ...money import Kobo

IndexMode = Literal["simulated", "live"]
MODES = ("simulated", "live")
REAL_MCP_URL = "https://index.mcp.paystack.africa/mcp"
ALLOWED_HOSTS = frozenset({"index.mcp.paystack.africa", "index.paystack.com"})
"""The only hosts an Index address may name: the MCP server and OAuth endpoints, and the page where the
person signs in."""
MIN_KEY_LENGTH = 32
DEFAULT_CAPS_KOBO: Mapping[str, Kobo] = MappingProxyType(
    {"airtime": 500_000, "electricity": 5_000_000, "food": 2_000_000}
)
"""What 234 lets one order through Index come to, by kind, below Index's own bounds (bounds.py)."""


@dataclass(frozen=True)
class IndexSettings:
    mode: IndexMode = "simulated"
    mcp_url: str = REAL_MCP_URL
    token_key: str | None = field(default=None, repr=False)
    caps_kobo: Mapping[str, Kobo] = DEFAULT_CAPS_KOBO

    @property
    def live(self) -> bool:
        return self.mode == "live"

    @classmethod
    def from_env(cls, read: Callable[[str], str | None]) -> IndexSettings:
        mode = _mode(read)
        key = (read("INDEX_TOKEN_KEY") or "").strip() or None
        if key is not None and len(key) < MIN_KEY_LENGTH:
            raise ConfigError(f"INDEX_TOKEN_KEY must be at least {MIN_KEY_LENGTH} characters.")
        url = (read("INDEX_MCP_URL") or "").strip() or None
        caps = _caps(read)
        if mode == "simulated":
            if url is not None:
                raise ConfigError(
                    "INDEX_MCP_URL is for INDEX_MODE=live: the simulator has its own address on this Worker."
                )
            return cls("simulated", REAL_MCP_URL, key, caps)
        if key is None:
            raise ConfigError("INDEX_MODE=live needs INDEX_TOKEN_KEY, the secret that seals people's tokens.")
        return cls("live", checked_url(url or REAL_MCP_URL), key, caps)


def checked_url(url: str) -> str:
    """The address, when it is https on one of Index's hosts and names no credentials, query or fragment."""
    parts = urlsplit(url)
    try:
        plain = parts.port in (None, 443) and not (
            parts.query or parts.fragment or parts.username or parts.password
        )
    except ValueError:
        plain = False
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or not plain:
        raise ConfigError(
            f"INDEX_MCP_URL must be an https address on {' or '.join(sorted(ALLOWED_HOSTS))}, got a host "
            "this build does not send people's tokens to."
        )
    return url.rstrip("/")


def _mode(read: Callable[[str], str | None]) -> IndexMode:
    raw = (read("INDEX_MODE") or "simulated").strip().lower()
    if raw not in MODES:
        raise ConfigError(f'INDEX_MODE must be "simulated" or "live", got "{raw}".')
    return cast(IndexMode, raw)


def _caps(read: Callable[[str], str | None]) -> Mapping[str, Kobo]:
    raw = (read("INDEX_CAPS_KOBO") or "").strip()
    if not raw:
        return DEFAULT_CAPS_KOBO
    try:
        given = json.loads(raw)
        assert isinstance(given, dict)
    except (ValueError, AssertionError) as error:
        raise ConfigError('INDEX_CAPS_KOBO must be JSON such as {"airtime": 500000}.') from error
    unknown = sorted(set(given) - set(DEFAULT_CAPS_KOBO))
    bad = [k for k, v in given.items() if not isinstance(v, int) or isinstance(v, bool) or v <= 0]
    if unknown or bad:
        raise ConfigError(
            f"INDEX_CAPS_KOBO names airtime, electricity and food, each a positive whole number of kobo; "
            f"got {', '.join(unknown + bad)}."
        )
    return MappingProxyType({**DEFAULT_CAPS_KOBO, **given})
