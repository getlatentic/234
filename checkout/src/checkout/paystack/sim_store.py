# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the simulated Paystack remembers, in D1, so every Worker instance sees the same state."""

import secrets
from dataclasses import dataclass
from typing import Any

from ..db import Db, UniqueViolation
from ..money import Kobo


@dataclass(frozen=True)
class SimTransaction:
    reference: str
    amount_kobo: Kobo
    currency: str
    email: str
    status: str
    gateway_response: str | None
    paid_at: str | None
    description: str


@dataclass(frozen=True)
class SimRecipient:
    recipient_code: str
    account_number: str
    bank_code: str
    name: str
    bank_name: str


@dataclass(frozen=True)
class SimTransfer:
    reference: str
    transfer_code: str
    recipient_code: str
    amount_kobo: Kobo
    status: str


def _transaction(row: dict[str, Any]) -> SimTransaction:
    return SimTransaction(
        row["reference"], row["amount_kobo"], row["currency"], row["email"], row["status"],
        row["gateway_response"], row["paid_at"], row["description"],
    )  # fmt: skip


def _recipient(row: dict[str, Any]) -> SimRecipient:
    return SimRecipient(
        row["recipient_code"], row["account_number"], row["bank_code"], row["name"], row["bank_name"]
    )


def _transfer(row: dict[str, Any]) -> SimTransfer:
    return SimTransfer(
        row["reference"], row["transfer_code"], row["recipient_code"], row["amount_kobo"], row["status"]
    )


class PaystackSimStore:
    def __init__(self, db: Db) -> None:
        self._db = db

    async def add_transaction(
        self, reference: str, amount_kobo: Kobo, currency: str, email: str, description: str
    ) -> bool:
        """False when the reference is taken."""
        try:
            await self._db.execute(
                "INSERT INTO sim_transactions (reference, amount_kobo, currency, email, status, description) "
                "VALUES (?, ?, ?, ?, 'abandoned', ?)",
                reference, amount_kobo, currency, email, description,
            )  # fmt: skip
        except UniqueViolation:
            return False
        return True

    async def transaction(self, reference: str) -> SimTransaction | None:
        row = await self._db.row("SELECT * FROM sim_transactions WHERE reference = ?", reference)
        return _transaction(row) if row else None

    async def open_transaction(self, reference: str) -> bool:
        """The checkout page was opened: an unpaid transaction reads `ongoing`."""
        changed = await self._db.execute(
            "UPDATE sim_transactions SET status = 'ongoing' WHERE reference = ? AND status = 'abandoned'",
            reference,
        )
        return changed == 1

    async def close_transaction(self, reference: str) -> bool:
        """The person closed the page without paying."""
        changed = await self._db.execute(
            "UPDATE sim_transactions SET status = 'abandoned' WHERE reference = ? AND status = 'ongoing'",
            reference,
        )
        return changed == 1

    async def finish_transaction(self, reference: str, paid: bool, paid_at: str) -> bool:
        """The checkout page's buttons. Only an unpaid transaction can be finished, once."""
        changed = await self._db.execute(
            "UPDATE sim_transactions SET status = ?, gateway_response = ?, paid_at = ? "
            "WHERE reference = ? AND status IN ('abandoned', 'ongoing')",
            "success" if paid else "failed",
            "Successful" if paid else "Declined",
            paid_at if paid else None,
            reference,
        )
        return changed == 1

    async def recipient_by_account(self, account_number: str, bank_code: str) -> SimRecipient | None:
        row = await self._db.row(
            "SELECT * FROM sim_recipients WHERE account_number = ? AND bank_code = ?",
            account_number,
            bank_code,
        )
        return _recipient(row) if row else None

    async def recipient_by_code(self, recipient_code: str) -> SimRecipient | None:
        row = await self._db.row("SELECT * FROM sim_recipients WHERE recipient_code = ?", recipient_code)
        return _recipient(row) if row else None

    async def ensure_recipient(
        self, account_number: str, bank_code: str, name: str, bank_name: str
    ) -> SimRecipient:
        """The recipient for an account, made once: a racing caller finds the winner's row."""
        await self._db.execute(
            "INSERT OR IGNORE INTO sim_recipients (recipient_code, account_number, bank_code, name, "
            "bank_name) "
            "VALUES (?, ?, ?, ?, ?)",
            f"RCP_{secrets.token_hex(8)}", account_number, bank_code, name, bank_name,
        )  # fmt: skip
        found = await self.recipient_by_account(account_number, bank_code)
        if found is None:
            raise RuntimeError("recipient vanished")
        return found

    async def transfer_by_reference(self, reference: str) -> SimTransfer | None:
        row = await self._db.row("SELECT * FROM sim_transfers WHERE reference = ?", reference)
        return _transfer(row) if row else None

    async def transfer_by_code(self, transfer_code: str) -> SimTransfer | None:
        row = await self._db.row("SELECT * FROM sim_transfers WHERE transfer_code = ?", transfer_code)
        return _transfer(row) if row else None

    async def ensure_transfer(
        self, reference: str, recipient_code: str, amount_kobo: Kobo, status: str
    ) -> SimTransfer:
        """The transfer for a reference, made once: a repeat of the reference finds the first."""
        await self._db.execute(
            "INSERT OR IGNORE INTO sim_transfers (reference, transfer_code, recipient_code, amount_kobo, "
            "status) "
            "VALUES (?, ?, ?, ?, ?)",
            reference, f"TRF_{secrets.token_hex(8)}", recipient_code, amount_kobo, status,
        )  # fmt: skip
        found = await self.transfer_by_reference(reference)
        if found is None:
            raise RuntimeError("transfer vanished")
        return found

    async def finalize_transfer(self, transfer_code: str) -> bool:
        changed = await self._db.execute(
            "UPDATE sim_transfers SET status = 'success' WHERE transfer_code = ? AND status = 'otp'",
            transfer_code,
        )
        return changed == 1
