# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a card's resource may ask of the sandbox, and what the host gives it.

A resource declares external origins in `_meta.ui.csp` (ext-apps specification 2026-01-26, "Resource
metadata"). The sandbox turns what it is sent into a Content-Security-Policy, so this module decides what is
sent: every entry must be a plain https origin (wss for connections) with an optional `*.` subdomain form and
port, at most 16 a field, and it must be on the host's own allowlist. What is refused is logged, never shown.
The same rules are in `sandbox/src/csp.js`, which checks again; `sandbox/test/csp-vectors.json` is run through
both.
"""

import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

FIELDS = ("connectDomains", "resourceDomains", "frameDomains", "baseUriDomains")
PERMISSIONS = ("camera", "microphone", "geolocation", "clipboardWrite")
MAX_ENTRIES = 16
SANDBOX_OPAQUE = "allow-scripts"
SANDBOX_ON_SANDBOX_ORIGIN = "allow-scripts allow-same-origin"

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOSTNAME = rf"(?:{_LABEL}\.)+[a-z](?:[a-z0-9-]{{0,61}}[a-z0-9])?"
_PORT = r"(?::[1-9][0-9]{0,4})?"
_SCHEMES = {"connectDomains": ("https", "wss")}
_SOURCES = {
    name: re.compile(rf"(?:{'|'.join(_SCHEMES.get(name, ('https',)))})://(?:\*\.)?{_HOSTNAME}{_PORT}")
    for name in FIELDS
}

log = logging.getLogger("chat.cards")


def refusal(name: str, entry: object) -> str | None:
    """Why an entry is not a source a server may declare for this field, or None when it is."""
    if not isinstance(entry, str):
        return "not a string"
    if len(entry) > 300:
        return "too long"
    if not _SOURCES[name].fullmatch(entry):
        return "not an https origin (wss for connections), with an optional *. subdomain and port"
    port = re.search(r":([0-9]+)$", entry)
    if port and int(port.group(1)) > 65535:
        return "port out of range"
    return None


@dataclass(frozen=True)
class OriginPolicy:
    """The host's allowlist: the origins any card may declare for each field, and the connectors whose
    `resourceDomains` are taken as they come (images of a real merchant) when they are plain origins."""

    allowed: Mapping[str, frozenset[str]] = field(default_factory=dict)
    trusted: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def permits(self, server: str, name: str, entry: str) -> bool:
        if entry in self.allowed.get(name, frozenset()):
            return True
        return name in self.trusted.get(server, frozenset()) and "*" not in entry

    def approved(self) -> dict[str, list[str]]:
        """What the host tells a view it approves, for `hostCapabilities.sandbox.csp`."""
        return {name: sorted(origins) for name, origins in self.allowed.items() if origins}


@dataclass(frozen=True)
class Refused:
    field: str
    entry: str
    reason: str


@dataclass(frozen=True)
class Declaration:
    """A resource's request, cut down to what the host grants."""

    csp: dict[str, list[str]] = field(default_factory=dict)
    permissions: dict[str, dict[str, Any]] = field(default_factory=dict)
    prefers_border: bool | None = None
    domain: str | None = None
    refused: tuple[Refused, ...] = ()

    @property
    def sandbox(self) -> str:
        """The flags of the frame the card runs in. It has no origin of its own, unless it embeds an approved
        third-party frame: a page like Paystack's popup builds and reads frames of its own, which needs the
        card to share the sandbox origin (a frame that is opaque cannot read the blank frame it makes)."""
        return SANDBOX_ON_SANDBOX_ORIGIN if self.csp.get("frameDomains") else SANDBOX_OPAQUE

    @property
    def hosts(self) -> list[str]:
        """The names a person is told the card loads content from, in the order declared."""
        return hosts_of(self.csp)


def hosts_of(csp: Mapping[str, Iterable[str]]) -> list[str]:
    names: list[str] = []
    for name in FIELDS:
        for entry in csp.get(name, ()):
            host = re.sub(r"^[a-z]+://", "", entry)
            host = re.sub(r":[0-9]+$", "", host)
            if host not in names:
                names.append(host)
    return names


def _entries(name: str, listed: object, server: str, policy: OriginPolicy) -> tuple[list[str], list[Refused]]:
    if not isinstance(listed, list):
        return [], [Refused(name, str(listed)[:80], "not a list")]
    kept: list[str] = []
    refused: list[Refused] = []
    for entry in listed:
        reason = "more than 16 entries" if len(kept) >= MAX_ENTRIES else refusal(name, entry)
        if reason is None and not policy.permits(server, name, entry):
            reason = "not on this host's allowlist"
        if reason:
            refused.append(Refused(name, str(entry)[:80], reason))
        elif entry not in kept:
            kept.append(entry)
    return kept, refused


def _permissions(asked: object, granted: frozenset[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(asked, dict):
        return {}
    return {name: {} for name in PERMISSIONS if name in asked and name in granted}


def resolve(ui: Mapping[str, Any], server: str, policy: OriginPolicy, granted: frozenset[str]) -> Declaration:
    """Reads `_meta.ui` of a resource. Nothing here raises for what a server sent: it is narrowed."""
    declared = ui.get("csp")
    declared = declared if isinstance(declared, dict) else {}
    csp: dict[str, list[str]] = {}
    refused: list[Refused] = []
    for name in FIELDS:
        if name not in declared:
            continue
        kept, dropped = _entries(name, declared[name], server, policy)
        refused.extend(dropped)
        if kept:
            csp[name] = kept
    border = ui.get("prefersBorder")
    domain = ui.get("domain")
    return Declaration(
        csp,
        _permissions(ui.get("permissions"), granted),
        border if isinstance(border, bool) else None,
        domain if isinstance(domain, str) else None,
        tuple(refused),
    )


def audit(server: str, uri: str, declaration: Declaration, asked: Mapping[str, Any]) -> None:
    """One line for what a card's resource asked and what it got, and one for each refused entry."""
    log.info(
        json.dumps(
            {
                "event": "card.csp",
                "server": server,
                "uri": uri,
                "csp": declaration.csp,
                "permissions": sorted(declaration.permissions),
                "asked_permissions": sorted(asked.get("permissions") or {})
                if isinstance(asked, dict)
                else [],
                "domain_ignored": declaration.domain,
            }
        )
    )
    for item in declaration.refused:
        log.warning(
            json.dumps(
                {
                    "event": "card.csp.refused",
                    "server": server,
                    "uri": uri,
                    "field": item.field,
                    "entry": item.entry,
                    "reason": item.reason,
                }
            )
        )
