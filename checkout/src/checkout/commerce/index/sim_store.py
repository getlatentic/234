# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated Index's state in D1 (migrations/0022_index.sql, `sim_index_*`): the Index accounts people
sign in as, the clients registered, the authorization codes and tokens it issued, every tool call it served
(with whether the call carried `confirmed`, which tests read to show that nothing charged before an approval),
the orders it placed, and a few settings the test routes turn."""

import json
import secrets
from dataclasses import dataclass
from typing import Any

from ...clock import Clock
from ...db import Db

CODE_TTL_MS = 5 * 60_000
ACCESS_TTL_MS = 60 * 60_000
REFRESH_TTL_MS = 30 * 24 * 60 * 60_000
START_ZAP_KOBO = 5_000_000


@dataclass(frozen=True)
class SimAccount:
    id: str
    name: str
    zap_linked: bool
    zap_kobo: int
    chowdeck_linked: bool
    chowdeck_phone: str | None


def _account_of(row: dict[str, Any]) -> SimAccount:
    return SimAccount(
        row["id"],
        row["name"],
        bool(row["zap_linked"]),
        row["zap_kobo"],
        bool(row["chowdeck_linked"]),
        row["chowdeck_phone"],
    )


def new_secret(prefix: str) -> str:
    return f"{prefix}-{secrets.token_urlsafe(24)}"


class IndexSimStore:
    def __init__(self, db: Db, clock: Clock) -> None:
        self._db, self._clock = db, clock

    async def new_account(self, name: str = "Ada Obi (simulated)") -> SimAccount:
        account = new_secret("acct")
        await self._db.execute(
            "INSERT INTO sim_index_account (id, name, zap_kobo, created_at) VALUES (?, ?, ?, ?)",
            account,
            name,
            START_ZAP_KOBO,
            self._clock.now(),
        )
        return SimAccount(account, name, True, START_ZAP_KOBO, False, None)

    async def account(self, account_id: str) -> SimAccount | None:
        row = await self._db.row("SELECT * FROM sim_index_account WHERE id = ?", account_id)
        return _account_of(row) if row else None

    async def latest_account(self) -> SimAccount | None:
        row = await self._db.row(
            "SELECT * FROM sim_index_account ORDER BY created_at DESC, rowid DESC LIMIT 1"
        )
        return _account_of(row) if row else None

    async def set_account(self, account_id: str, **columns: object) -> None:
        allowed = {"zap_linked", "zap_kobo", "chowdeck_linked", "chowdeck_phone"}
        names = [name for name in columns if name in allowed]
        sets = ", ".join(f"{name} = ?" for name in names)
        await self._db.execute(
            f"UPDATE sim_index_account SET {sets} WHERE id = ?", *[columns[n] for n in names], account_id
        )

    async def debit(self, account_id: str, kobo: int) -> bool:
        """Takes `kobo` from Zap only if it holds that much."""
        changed = await self._db.execute(
            "UPDATE sim_index_account SET zap_kobo = zap_kobo - ? WHERE id = ? AND zap_linked = 1 "
            "AND zap_kobo >= ?",
            kobo,
            account_id,
            kobo,
        )
        return changed == 1

    async def register_client(self, redirect_uris: list[str]) -> tuple[str, str]:
        client, secret = new_secret("client"), new_secret("secret")
        await self._db.execute(
            "INSERT INTO sim_index_client (client_id, secret, redirect_uris, created_at) VALUES (?, ?, ?, ?)",
            client,
            secret,
            json.dumps(redirect_uris),
            self._clock.now(),
        )
        return client, secret

    async def client(self, client_id: str) -> dict[str, Any] | None:
        row = await self._db.row("SELECT * FROM sim_index_client WHERE client_id = ?", client_id)
        return {**row, "redirect_uris": json.loads(row["redirect_uris"])} if row else None

    async def issue_code(self, client_id: str, account_id: str, redirect_uri: str, challenge: str) -> str:
        code = new_secret("code")
        await self._db.execute(
            "INSERT INTO sim_index_grant (code, client_id, account_id, redirect_uri, challenge, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            code,
            client_id,
            account_id,
            redirect_uri,
            challenge,
            self._clock.now() + CODE_TTL_MS,
        )
        return code

    async def take_code(self, code: str) -> dict[str, Any] | None:
        """The grant behind a code, used up by this call; a code used before, or late, gives nothing."""
        row = await self._db.row("SELECT * FROM sim_index_grant WHERE code = ?", code)
        if row is None:
            return None
        used = await self._db.execute(
            "UPDATE sim_index_grant SET used = 1 WHERE code = ? AND used = 0 AND expires_at > ?",
            code,
            self._clock.now(),
        )
        return row if used == 1 else None

    async def issue_tokens(
        self, client_id: str, account_id: str | None, refresh: bool = True
    ) -> dict[str, Any]:
        now, access = self._clock.now(), new_secret("at")
        await self._db.execute(
            "INSERT INTO sim_index_token (token, kind, client_id, account_id, expires_at) VALUES (?, 'access', ?, ?, ?)",
            access,
            client_id,
            account_id,
            now + ACCESS_TTL_MS,
        )
        body: dict[str, Any] = {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": ACCESS_TTL_MS // 1000,
            "scope": "mcp:transact",
        }
        if refresh:
            body["refresh_token"] = new_secret("rt")
            await self._db.execute(
                "INSERT INTO sim_index_token (token, kind, client_id, account_id, expires_at) "
                "VALUES (?, 'refresh', ?, ?, ?)",
                body["refresh_token"],
                client_id,
                account_id,
                now + REFRESH_TTL_MS,
            )
        return body

    async def live_token(self, token: str, kind: str) -> dict[str, Any] | None:
        return await self._db.row(
            "SELECT * FROM sim_index_token WHERE token = ? AND kind = ? AND revoked = 0 AND expires_at > ?",
            token,
            kind,
            self._clock.now(),
        )

    async def spend_refresh(self, token: str) -> dict[str, Any] | None:
        """A refresh token is good once: the next refresh gets a new one (rotation)."""
        row = await self.live_token(token, "refresh")
        if row is None:
            return None
        spent = await self._db.execute(
            "UPDATE sim_index_token SET revoked = 1 WHERE token = ? AND revoked = 0", token
        )
        return row if spent == 1 else None

    async def revoke(self, token: str) -> bool:
        return await self._db.execute("UPDATE sim_index_token SET revoked = 1 WHERE token = ?", token) == 1

    async def expire_access_tokens(self) -> None:
        await self._db.execute(
            "UPDATE sim_index_token SET expires_at = ? WHERE kind = 'access'", self._clock.now() - 1
        )

    async def revoke_all(self) -> None:
        await self._db.execute("UPDATE sim_index_token SET revoked = 1")

    async def record_call(self, account_id: str | None, tool: str, arguments: dict[str, Any]) -> None:
        await self._db.execute(
            "INSERT INTO sim_index_call (account_id, tool, arguments, confirmed, at) VALUES (?, ?, ?, ?, ?)",
            account_id,
            tool,
            json.dumps(arguments),
            1 if arguments.get("confirmed") is True else 0,
            self._clock.now(),
        )

    async def calls(self) -> list[dict[str, Any]]:
        rows = await self._db.rows("SELECT * FROM sim_index_call ORDER BY seq")
        return [
            {**row, "arguments": json.loads(row["arguments"]), "confirmed": bool(row["confirmed"])}
            for row in rows
        ]

    async def add_order(
        self, account_id: str, tool: str, arguments: dict[str, Any], total: int, status: str, detail: dict
    ) -> str:
        order = new_secret("ord")
        await self._db.execute(
            "INSERT INTO sim_index_order (id, account_id, tool, arguments, total_kobo, status, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            order,
            account_id,
            tool,
            json.dumps(arguments),
            total,
            status,
            json.dumps(detail),
            self._clock.now(),
        )
        return order

    async def order(self, order_id: str, account_id: str) -> dict[str, Any] | None:
        row = await self._db.row(
            "SELECT * FROM sim_index_order WHERE id = ? AND account_id = ?", order_id, account_id
        )
        return {**row, "detail": json.loads(row["detail"])} if row else None

    async def orders(self, account_id: str) -> list[dict[str, Any]]:
        rows = await self._db.rows(
            "SELECT * FROM sim_index_order WHERE account_id = ? ORDER BY created_at", account_id
        )
        return [{**row, "detail": json.loads(row["detail"])} for row in rows]

    async def setting(self, name: str, fallback: str) -> str:
        row = await self._db.row("SELECT value FROM sim_index_setting WHERE name = ?", name)
        return row["value"] if row else fallback

    async def set_setting(self, name: str, value: str) -> None:
        await self._db.execute(
            "INSERT INTO sim_index_setting (name, value) VALUES (?, ?) "
            "ON CONFLICT (name) DO UPDATE SET value = excluded.value",
            name,
            value,
        )
