# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a turn may be shown and may call. Three things decide it: the chat's connectors (scope.py), whether
its owner is an account, and, for a turn a personal agent asked for over PACT (pact/), the scopes on the
message that drove it.

A turn the web page or an A2A caller drove carries no scopes and may do all its owner may. A PACT turn may
use, as the person's account, only what their delegation token grants. It is shown the memory tools even
without a scope, so that a request needing a note becomes a step-up: the call is refused, and the refusal
names the scopes it needs. A PACT turn that is not delegated runs as the agent's own owner (`p:`), whose
payments need no scope because they are not the person's account."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from . import kinds, scope, sources, wallet
from .eventlog import Event
from .hub import MEMORY_SERVER, SEPARATOR, ToolOutcome, refused
from .ledger_owner import is_account
from .memory import NOT_AN_ACCOUNT, is_memory_tool, shown

MEMORY_READ, MEMORY_WRITE, PAYMENTS = "memory:read", "memory:write", "payments"
SCOPES = {
    MEMORY_READ: "See what you asked 234 to remember: saved recipients, preferences and facts.",
    MEMORY_WRITE: "Offer to remember, change or forget something for you. You press Save on each one.",
    PAYMENTS: "Prepare payments, purchases and transfers from your 234 account, and check how they stand. "
    "You approve every payment on a card.",
}
READS_MEMORY = frozenset({f"{MEMORY_SERVER}{SEPARATOR}recall"})
NEEDS_PERMISSION = (
    "The person has not allowed this yet: it needs {scopes}. They are being asked for it now. Say in one "
    "sentence what you need it for, and call no other tool."
)
SCOPES_FIELD = "scopes"
MISSING_FIELD = "missing_scopes"
USED_FIELD = "scope"


def scopes_of(connectors: Iterable[str]) -> dict[str, str]:
    """The scopes a Brand with these connectors offers, with what each lets an agent do."""
    names = set(connectors)
    kept = {MEMORY_READ, MEMORY_WRITE} if MEMORY_SERVER in names else set()
    kept |= {PAYMENTS} if names - {MEMORY_SERVER} else set()
    return {name: description for name, description in SCOPES.items() if name in kept}


@dataclass(frozen=True)
class Refusal:
    outcome: ToolOutcome
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class Permissions:
    owner: str
    servers: tuple[str, ...] = ()
    scopes: frozenset[str] | None = None
    """None for a turn no personal agent asked for."""
    reading: sources.Reading = sources.NOTHING_READ
    """What the turn has read from sources so far."""

    @property
    def account(self) -> bool:
        return is_account(self.owner)

    @property
    def reads_notes(self) -> bool:
        return self.account and (self.scopes is None or MEMORY_READ in self.scopes)

    @property
    def memory_tools(self) -> bool:
        return self.account or self.scopes is not None

    def tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        offered = wallet.kept(shown(tools, self.memory_tools, self.reads_notes), self.account)
        return scope.within(offered, self.servers)

    def needed(self, qualified: str) -> str | None:
        """The scope a call needs in this turn, if any."""
        if self.scopes is None or sources.reads_only(qualified):
            return None
        if is_memory_tool(qualified):
            return MEMORY_READ if qualified in READS_MEMORY else MEMORY_WRITE
        return PAYMENTS if self.account else None

    def refusal(self, qualified: str) -> Refusal | None:
        """Why this call may not run, or None when it may."""
        server, _, tool = qualified.partition(SEPARATOR)
        if not scope.allows(qualified, self.servers):
            return Refusal(refused(server, tool, scope.OUTSIDE))
        needed = self.needed(qualified)
        if needed is not None and needed not in (self.scopes or ()):
            return Refusal(refused(server, tool, NEEDS_PERMISSION.format(scopes=needed)), (needed,))
        if is_memory_tool(qualified) and not self.account:
            return Refusal(refused(server, tool, NOT_AN_ACCOUNT))
        if wallet.is_wallet_tool(qualified) and not self.account:
            return Refusal(refused(server, tool, wallet.NOT_AN_ACCOUNT))
        return None


def marks(permits: Permissions, qualified: str, refusal: Refusal | None) -> dict[str, Any]:
    """What a tool event records about scopes: the ones a refused call needed, or the one a call ran under
    (pact/receipts.py reads both)."""
    if refusal is not None:
        return {MISSING_FIELD: list(refusal.missing)} if refusal.missing else {}
    needed = permits.needed(qualified)
    return {USED_FIELD: needed} if needed else {}


def of(owner: str, servers: tuple[str, ...], events: list[Event]) -> Permissions:
    """The permissions of the turn the last input in the log drives: its scopes are those on the latest
    message the person or their agent sent."""
    said = next((e for e in reversed(events) if e.type == kinds.USER), None)
    listed = said.payload.get(SCOPES_FIELD) if said else None
    scopes = frozenset(listed) if isinstance(listed, list) else None
    return Permissions(owner, servers, scopes, sources.reading_of(events))
