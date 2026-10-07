# SPDX-License-Identifier: AGPL-3.0-or-later
"""The connector's rows (reach/models.py), read and written with the turn runner's own SQL. Every statement
names the ledger owner key, so one person's rows are never another's."""

import json
from dataclasses import dataclass
from typing import Any

from ..db import Db


@dataclass(frozen=True)
class Delegation:
    brand_name: str
    access_token: str
    refresh_token: str
    scopes: tuple[str, ...]
    expires_at: int


@dataclass(frozen=True)
class SignIn:
    id: str
    owner: str
    brand: str
    device_code: str
    link: str
    scopes: tuple[str, ...]
    interval: int
    expires_at: int
    polled_at: int
    state: str


class Store:
    def __init__(self, db: Db) -> None:
        self._db = db

    async def context(self, owner: str, brand: str) -> str | None:
        row = await self._db.row(
            "SELECT context_id FROM reach_conversation WHERE owner = ? AND brand = ?", owner, brand
        )
        return row["context_id"] if row else None

    async def keep_context(self, owner: str, brand: str, context_id: str, now: int) -> None:
        await self._db.execute(
            "INSERT INTO reach_conversation (owner, brand, context_id, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (owner, brand) DO UPDATE SET context_id = excluded.context_id, "
            "updated_at = excluded.updated_at",
            owner, brand, context_id, now,
        )  # fmt: skip

    async def forget_context(self, owner: str, brand: str) -> None:
        await self._db.execute("DELETE FROM reach_conversation WHERE owner = ? AND brand = ?", owner, brand)

    async def delegation(self, owner: str, brand: str) -> Delegation | None:
        row = await self._db.row(
            "SELECT brand_name, access_token, refresh_token, scopes, expires_at FROM reach_delegation "
            "WHERE owner = ? AND brand = ?",
            owner, brand,
        )  # fmt: skip
        if row is None:
            return None
        scopes = tuple(row["scopes"].split())
        return Delegation(
            row["brand_name"], row["access_token"], row["refresh_token"], scopes, int(row["expires_at"])
        )

    async def keep_delegation(self, owner: str, brand: str, given: Delegation, now: int) -> None:
        await self._db.execute(
            "INSERT INTO reach_delegation (owner, brand, brand_name, access_token, refresh_token, scopes, "
            "expires_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (owner, brand) DO UPDATE SET brand_name = excluded.brand_name, "
            "access_token = excluded.access_token, "
            "refresh_token = excluded.refresh_token, "
            "scopes = excluded.scopes, expires_at = excluded.expires_at, updated_at = excluded.updated_at",
            owner, brand, given.brand_name, given.access_token, given.refresh_token, " ".join(given.scopes),
            given.expires_at, now,
        )  # fmt: skip

    async def forget_delegation(self, owner: str, brand: str) -> None:
        await self._db.execute("DELETE FROM reach_delegation WHERE owner = ? AND brand = ?", owner, brand)

    async def start_sign_in(self, sign_in: SignIn, now: int) -> None:
        await self._db.execute(
            "INSERT INTO reach_signin (id, owner, brand, device_code, link, scopes, interval, expires_at, "
            "polled_at, state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            sign_in.id, sign_in.owner, sign_in.brand, sign_in.device_code, sign_in.link,
            " ".join(sign_in.scopes), sign_in.interval, sign_in.expires_at, sign_in.polled_at, sign_in.state,
            now,
        )  # fmt: skip

    async def sign_in(self, owner: str, sign_in_id: str) -> SignIn | None:
        row = await self._db.row("SELECT * FROM reach_signin WHERE id = ? AND owner = ?", sign_in_id, owner)
        if row is None:
            return None
        return SignIn(
            row["id"], row["owner"], row["brand"], row["device_code"], row["link"],
            tuple(row["scopes"].split()), int(row["interval"]), int(row["expires_at"]), int(row["polled_at"]),
            row["state"],
        )  # fmt: skip

    async def polled(self, sign_in_id: str, at_ms: int) -> None:
        await self._db.execute("UPDATE reach_signin SET polled_at = ? WHERE id = ?", at_ms, sign_in_id)

    async def settle(self, sign_in_id: str, state: str) -> tuple[str, bool]:
        """Ends a pending sign-in in `state`; whatever ended it first stands. The state it ended in, and
        whether this call ended it."""
        mine = await self._db.rows(
            "UPDATE reach_signin SET state = ? WHERE id = ? AND state = 'pending' RETURNING id",
            state, sign_in_id,
        )  # fmt: skip
        row = await self._db.row("SELECT state FROM reach_signin WHERE id = ?", sign_in_id)
        return (row["state"] if row else state), bool(mine)

    async def keep_receipt(self, owner: str, brand: str, receipt: dict[str, Any], now: int) -> None:
        await self._db.execute(
            "INSERT INTO reach_receipt (owner, brand, claims, jws, created_at) VALUES (?, ?, ?, ?, ?)",
            owner, brand, json.dumps(receipt["claims"]), receipt["jws"], now,
        )  # fmt: skip
