# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT §5.6: the receipt on every reply served under a delegation token. It says which grant and which
account the turn ran as, for which agent and Brand, which scopes its tool calls used and which tools ran,
each with a digest of its arguments, signed with the key that signs the tokens."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from turns import kinds, permissions
from turns.eventlog import Event

from . import addresses, signing
from .brands import Brand
from .delegation import Delegation
from .identity import Caller


def _arguments_hash(arguments: Any) -> str:
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def receipt(
    delegation: Delegation, brand: Brand, caller: Caller, events: list[Event], now: float
) -> dict[str, Any]:
    """`events`: the turn's events; the tools that ran are those marked with the scope they used."""
    ran = [e.payload for e in events if e.type == kinds.TOOL and permissions.USED_FIELD in e.payload]
    claims = {
        "grantId": delegation.grant_id,
        "user": delegation.account,
        "pa": caller.issuer,
        "brand": addresses.interface_url(brand),
        "scopesUsed": sorted({p[permissions.USED_FIELD] for p in ran}),
        "actions": [
            {"tool": f"{p['server']}__{p['tool']}", "argsHash": _arguments_hash(p.get("arguments", {}))}
            for p in ran
        ],
        "ts": datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return {"jws": signing.sign(claims), "claims": claims}
