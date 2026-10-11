# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the simulated Paystack remembers, in D1, so every Worker instance sees the same state."""

import secrets
from dataclasses import dataclass
from typing import Any

from ..db import Db, UniqueViolation
from ..money import Kobo


@dataclass(frozen=True)
class SimTransaction:
    id: int
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


@dataclass(frozen=True)
class SimRefund:
    id: int
    transaction_id: int
    transaction_reference: str
    amount_kobo: Kobo
    currency: str
    status: str


def _transaction(row: dict[str, Any]) -> SimTransaction:
    return SimTransaction(
        row["id"], row["reference"], row["amount_kobo"], row["currency"], row["email"], row["status"],
        row["gateway_response"], row["paid_at"], row["description"],
    )  # fmt: skip


def _refund(row: dict[str, Any]) -> SimRefund:
    return SimRefund(
        row["id"], row["transaction_id"], row["transaction_reference"], row["amount_kobo"], row["currency"],
        row["status"],
    )  # fmt: skip


_TRANSACTION = "SELECT rowid AS id, * FROM sim_transactions "
_REFUND = (
    "SELECT r.*, t.rowid AS transaction_id FROM sim_refunds AS r "
    "JOIN sim_transactions AS t ON t.reference = r.transaction_reference "
)
_ADD_REFUND = (
    "INSERT INTO sim_refunds (id, transaction_reference, amount_kobo, currency, status, merchant_note, "
    "customer_note) "
    "SELECT ?, t.reference, ?, t.currency, 'pending', ?, ? FROM sim_transactions AS t "
    "WHERE t.reference = ? AND t.status = 'success' AND ? + (SELECT COALESCE(SUM(r.amount_kobo), 0) "
    "FROM sim_refunds AS r WHERE r.transaction_reference = t.reference AND r.status <> 'failed') "
    "<= t.amount_kobo"
)


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
        row = await self._db.row(f"{_TRANSACTION}WHERE reference = ?", reference)
        return _transaction(row) if row else None

    async def transaction_by_id(self, transaction_id: int) -> SimTransaction | None:
        row = await self._db.row(f"{_TRANSACTION}WHERE rowid = ?", transaction_id)
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

    async def add_refund(
        self, reference: str, amount_kobo: Kobo, merchant_note: str | None, customer_note: str | None
    ) -> SimRefund | None:
        """A refund of a paid transaction, as Paystack makes one: pending, and never more than what is left of
        the payment once the refunds that did not fail are counted, in the one statement that makes it."""
        refund_id = secrets.randbelow(900_000_000) + 100_000_000
        changed = await self._db.execute(
            _ADD_REFUND, refund_id, amount_kobo, merchant_note, customer_note, reference, amount_kobo
        )
        return await self.refund(refund_id) if changed == 1 else None

    async def refund(self, refund_id: int) -> SimRefund | None:
        row = await self._db.row(f"{_REFUND}WHERE r.id = ?", refund_id)
        return _refund(row) if row else None

    async def refunds_of(self, transaction_id: int) -> list[SimRefund]:
        rows = await self._db.rows(f"{_REFUND}WHERE t.rowid = ? ORDER BY r.id", transaction_id)
        return [_refund(row) for row in rows]

    async def set_refund_status(self, reference: str, status: str) -> int:
        """The test routes move a transaction's undecided refunds on; how many moved."""
        return await self._db.execute(
            "UPDATE sim_refunds SET status = ? WHERE transaction_reference = ? "
            "AND status IN ('pending', 'processing', 'needs-attention')",
            status,
            reference,
        )
