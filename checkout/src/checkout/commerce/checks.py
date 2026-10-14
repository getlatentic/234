# SPDX-License-Identifier: AGPL-3.0-or-later
"""Account checks (docs/commerce.md, "Account check", rule 5): what a provider found for the account a buyer
typed, kept for one owner with an id. A quote for a merchant that checks accounts carries one, takes the
holder's name from it and nowhere else, and is refused if it was made for another owner, another merchant,
other fields, or has expired. The same account checked again while a check is live gives that check back."""

import json
import secrets
from collections.abc import Callable, Mapping
from typing import Any

from ..clock import Clock
from ..db import Db
from ..errors import DomainError
from .model import AccountCheck, Merchant
from .provider import AccountLookup
from .text import third_party

CHECK_TTL_MS = 15 * 60_000
HOLDER_LIMIT = 120


def new_check_id() -> str:
    return f"ck-{secrets.token_hex(10)}"


def canonical(fields: Mapping[str, Any]) -> str:
    return json.dumps(dict(sorted(fields.items())), separators=(",", ":"), ensure_ascii=False)


def _check_of(row: dict[str, Any]) -> AccountCheck:
    return AccountCheck(
        row["id"],
        row["merchant_id"],
        row["holder_name"],
        row["due_kobo"],
        json.loads(row["fields"]),
        row["created_at"],
        row["expires_at"],
        json.loads(row["detail"]),
    )


class AccountChecks:
    def __init__(self, db: Db, clock: Clock, owner: Callable[[], str]) -> None:
        self._db, self._clock, self._owner = db, clock, owner

    async def record(
        self,
        merchant: Merchant,
        fields: Mapping[str, str],
        found: AccountLookup,
        carried: Mapping[str, str] | None = None,
    ) -> AccountCheck:
        """The check for this owner, merchant, fields and holder: the live one if any, else a new one.
        `carried` is what the person gave beside the account (a phone), kept for the quote that follows."""
        owner, now = self._owner(), self._clock.now()
        holder, wanted = third_party(found.holder_name, HOLDER_LIMIT), canonical(fields)
        stored = {**found.detail, **({"carried": dict(carried)} if carried else {})}
        detail = canonical(stored)
        live = await self._db.row(
            "SELECT * FROM account_check WHERE owner = ? AND merchant_id = ? AND fields = ? "
            "AND holder_name = ? AND detail = ? "
            "AND (due_kobo IS ? ) AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
            owner,
            merchant.id,
            wanted,
            holder,
            detail,
            found.due_kobo,
            now,
        )
        if live:
            return _check_of(live)
        check_id = new_check_id()
        await self._db.execute(
            "INSERT INTO account_check (id, owner, merchant_id, fields, holder_name, detail, due_kobo, "
            "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            check_id,
            owner,
            merchant.id,
            wanted,
            holder,
            detail,
            found.due_kobo,
            now,
            now + CHECK_TTL_MS,
        )
        return AccountCheck(
            check_id,
            merchant.id,
            holder,
            found.due_kobo,
            dict(fields),
            now,
            now + CHECK_TTL_MS,
            stored,
        )

    async def fields_of(self, check_id: str, merchant: Merchant) -> dict[str, str]:
        """What this owner's check `check_id` at `merchant` was made for, with the fields given beside it (a
        phone), so a quote need not repeat them; none when there is no such check."""
        row = await self._db.row(
            "SELECT * FROM account_check WHERE id = ? AND owner = ? AND merchant_id = ?",
            check_id,
            self._owner(),
            merchant.id,
        )
        if row is None:
            return {}
        check = _check_of(row)
        return {**check.detail.get("carried", {}), **check.fields}

    async def require(
        self, check_id: str | None, merchant: Merchant, fields: Mapping[str, str]
    ) -> AccountCheck:
        """The check a quote for `merchant` and `fields` carries, or why there is none."""
        if check_id is None:
            raise DomainError(
                "ACCOUNT_CHECK_REQUIRED",
                f"{merchant.name} checks the account before a quote. Call check_account with the details, "
                "show the person the holder's name, then pass its check_id.",
            )
        row = await self._db.row(
            "SELECT * FROM account_check WHERE id = ? AND owner = ?", check_id, self._owner()
        )
        if row is None:
            raise DomainError("CHECK_NOT_FOUND", f"There is no account check {check_id}. Call check_account.")
        check = _check_of(row)
        if check.merchant_id != merchant.id or any(fields.get(k) != v for k, v in check.fields.items()):
            raise DomainError(
                "CHECK_MISMATCH",
                "That account check was made for other details. Call check_account again for these.",
            )
        if check.expires_at <= self._clock.now():
            raise DomainError("CHECK_EXPIRED", "That account check has expired. Call check_account again.")
        return check
