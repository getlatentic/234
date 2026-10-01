# SPDX-License-Identifier: AGPL-3.0-or-later
"""An entry as the connector holds it, and the two ways it is shown: to the model (never the account number)
and to its owner in their own notes (the whole entry)."""

from dataclasses import dataclass
from typing import Any

from ..mask import mask_account
from ..paystack.bank_names import bank_of_code

KINDS = ("recipient", "preference", "fact")
SOURCE_BY_KIND = {"recipient": "card", "preference": "stated", "fact": "stated"}


@dataclass(frozen=True)
class Entry:
    id: str
    kind: str
    title: str
    hook: str
    body: str
    source: str
    created_at: int
    updated_at: int
    last_used: int
    bank_code: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    verified_at: int | None = None
    deleted_at: int | None = None

    @classmethod
    def of(cls, row: dict[str, Any]) -> Entry:
        names = cls.__dataclass_fields__
        return cls(**{name: row[name] for name in names})

    @property
    def bank_name(self) -> str | None:
        bank = bank_of_code(self.bank_code) if self.bank_code else None
        return bank.name if bank else None

    def for_model(self) -> dict[str, Any]:
        """What the model may read of an entry: a recipient's account number only masked, never whole."""
        shown: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "hook": self.hook,
            "body": self.body,
        }
        if self.kind == "recipient" and self.account_number:
            shown |= {
                "bank": self.bank_name,
                "account_name": self.account_name,
                "account_masked": mask_account(self.account_number),
            }
        return shown

    def for_owner(self) -> dict[str, Any]:
        """The whole entry, for its owner's own list and export."""
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "hook": self.hook,
            "body": self.body,
            "source": self.source,
            "bank_code": self.bank_code,
            "bank": self.bank_name,
            "account_number": self.account_number,
            "account_name": self.account_name,
            "verified_at": self.verified_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_used": self.last_used,
        }
