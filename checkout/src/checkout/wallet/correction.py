# SPDX-License-Identifier: AGPL-3.0-or-later
"""A correction as an operator asks for it (POST /ops/wallet/adjust), and as 234 keeps it
(migrations/0017_wallet_adjustment.sql). The terms are the owner, the direction, the amount and the reason:
a second operator applies a proposal only by naming the same correction id with the same terms."""

import re
from dataclasses import dataclass
from typing import Any

from ..errors import DomainError
from ..money import Kobo
from ..owner import is_owner_key

SIGNS = {"credit": 1, "debit": -1}
DIRECTIONS = {sign: direction for direction, sign in SIGNS.items()}
REASON_MAX = 500
OPERATOR_MAX = 64
_CORRECTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")


@dataclass(frozen=True)
class Correction:
    correction_id: str
    owner: str
    sign: int
    amount_kobo: Kobo
    reason: str
    operator: str

    def terms(self) -> tuple[str, int, Kobo, str]:
        return self.owner, self.sign, self.amount_kobo, self.reason


@dataclass(frozen=True)
class Adjustment:
    correction_id: str
    owner: str
    sign: int
    amount_kobo: Kobo
    reason: str
    proposed_by: str
    approved_by: str | None
    state: str
    created_at: int
    applied_at: int | None

    def terms(self) -> tuple[str, int, Kobo, str]:
        return self.owner, self.sign, self.amount_kobo, self.reason

    def view(self) -> dict[str, Any]:
        """What the operator is answered: no owner, which the operator already holds."""
        return {
            "correctionId": self.correction_id,
            "direction": DIRECTIONS[self.sign],
            "amountKobo": self.amount_kobo,
            "reason": self.reason,
            "state": self.state,
            "proposedBy": self.proposed_by,
            "approvedBy": self.approved_by,
        }


def adjustment_of(row: dict[str, Any]) -> Adjustment:
    return Adjustment(
        row["correction_id"], row["owner"], row["sign"], row["amount_kobo"], row["reason"],
        row["proposed_by"], row["approved_by"], row["state"], row["created_at"], row["applied_at"],
    )  # fmt: skip


def _refused(message: str) -> DomainError:
    return DomainError("INVALID_INPUT", message)


def _text(body: dict[str, Any], name: str, most: int) -> str:
    value = body.get(name)
    text = value.strip() if isinstance(value, str) else ""
    if not text or len(text) > most:
        raise _refused(f"{name} is required: at most {most} characters.")
    return text


def correction_of(body: Any) -> Correction:
    """The correction a request body asks for, or INVALID_INPUT naming the first thing wrong with it."""
    if not isinstance(body, dict):
        raise _refused("The body is a JSON object.")
    correction_id, owner = body.get("correction_id"), body.get("owner")
    if not isinstance(correction_id, str) or not _CORRECTION_ID.fullmatch(correction_id):
        raise _refused("correction_id is 1 to 64 letters, digits, '.', '_', ':' or '-'.")
    if not is_owner_key(owner):
        raise _refused("owner is 32 lowercase hex characters.")
    if body.get("direction") not in SIGNS:
        raise _refused("direction is credit or debit.")
    amount = body.get("amount_kobo")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise _refused("amount_kobo is a positive whole number of kobo.")
    return Correction(
        correction_id,
        owner,
        SIGNS[body["direction"]],
        amount,
        _text(body, "reason", REASON_MAX),
        _text(body, "operator", OPERATOR_MAX),
    )
