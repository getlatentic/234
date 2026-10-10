# SPDX-License-Identifier: AGPL-3.0-or-later
"""A withdrawal as 234 keeps it (migrations/0014_wallet_withdrawal.sql), and as a card may see it: the
account number masked, never whole."""

from dataclasses import dataclass
from typing import Any

from ..mask import mask_account
from ..money import Kobo, format_naira

UNDECIDED = "sent"
GIVEN_BACK = ("failed", "reversed")
WORDS = {
    "open": "Confirm the name",
    "expired": "Expired",
    "sent": "Sending",
    "succeeded": "Withdrawn",
    "failed": "Returned",
    "reversed": "Returned",
}


@dataclass(frozen=True)
class Withdrawal:
    id: str
    owner: str
    amount_kobo: Kobo
    bank_code: str
    bank_name: str | None
    account_number: str
    account_name: str
    recipient_code: str
    state: str
    transfer_code: str | None
    transfer_status: str | None
    sending_since: int | None
    created_at: int
    expires_at: int
    name_confirmed_at: int | None
    decided_at: int | None


def withdrawal_of(row: dict[str, Any]) -> Withdrawal:
    return Withdrawal(**{name: row[name] for name in Withdrawal.__dataclass_fields__})


def withdrawal_view(withdrawal: Withdrawal) -> dict[str, Any]:
    """What the wallet card shows of a withdrawal."""
    return {
        "id": withdrawal.id,
        "amountKobo": withdrawal.amount_kobo,
        "amount": format_naira(withdrawal.amount_kobo),
        "bank": withdrawal.bank_name or withdrawal.bank_code,
        "accountMasked": mask_account(withdrawal.account_number),
        "accountName": withdrawal.account_name,
        "state": withdrawal.state,
        "status": WORDS[withdrawal.state],
    }
