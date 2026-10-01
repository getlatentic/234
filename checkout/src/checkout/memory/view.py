# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a memory card shows, as structured content: a line of what will be saved (or was), who it is for, and
where the decision stands. The card draws only this; the entry's account number is never in it."""

from typing import Any

from ..mask import mask_account

PENDING, SAVED, DISCARDED, EXPIRED, REFUSED = "pending", "saved", "discarded", "expired", "refused"
FORGOTTEN, RESTORED = "forgotten", "restored"


def _what(op: str, kind: str, title: str, hook: str) -> str:
    if op == "forget":
        return title
    if kind == "recipient":
        return title
    return f"{title}: {hook}"


def _detail(payload: dict[str, Any]) -> str:
    if payload.get("kind") != "recipient" or "account_number" not in payload:
        return ""
    ending = mask_account(payload["account_number"])[-4:]
    bank = payload.get("bank_name") or ""
    return " · ".join(part for part in (payload["account_name"], bank, f"ending {ending}") if part)


def proposal_view(
    proposal_id: str, op: str, state: str, payload: dict[str, Any], note: str = ""
) -> dict[str, Any]:
    """`payload` is the proposal's content, with `bank_name` added for a recipient."""
    return {
        "proposal_id": proposal_id,
        "memory": {
            "op": op,
            "state": state,
            "kind": payload["kind"],
            "title": payload["title"],
            "what": _what(op, payload["kind"], payload["title"], payload["hook"]),
            "detail": _detail(payload),
            "note": note,
        },
    }
