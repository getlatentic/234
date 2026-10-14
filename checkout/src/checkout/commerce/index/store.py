# SPDX-License-Identifier: AGPL-3.0-or-later
"""What 234 keeps about Index (migrations/0022_index.sql): the client it registered, and each person's
connection. Tokens are sealed on the way in and opened on the way out, with a context of the owner and the
column, so a row copied to another owner is unreadable. Every statement on a connection names its owner."""

import json
from dataclasses import dataclass, replace

from ...clock import Clock
from ...db import Db
from .oauth import Registration, Tokens
from .secretbox import SealError, SecretBox

REFRESH_CLAIM_MS = 30_000


@dataclass(frozen=True)
class Connection:
    owner: str
    tokens: Tokens
    client_id: str
    version: int
    linked: tuple[str, ...]
    """Merchants the person linked at Index through 234, by Index's id (Chowdeck)."""


def _context(owner: str, column: str) -> str:
    return f"index-connection\n{owner}\n{column}"


class IndexStore:
    def __init__(self, db: Db, clock: Clock, box: SecretBox) -> None:
        self._db, self._clock, self._box = db, clock, box

    async def registration(self, server: str, redirect_uri: str) -> Registration | None:
        row = await self._db.row(
            "SELECT client_id, secret_sealed, auth_method FROM index_client WHERE server = ? AND "
            "redirect_uri = ?",
            server,
            redirect_uri,
        )
        return self._registration_of(row, server, redirect_uri) if row else None

    async def registration_of_client(self, client_id: str) -> Registration | None:
        row = await self._db.row(
            "SELECT server, redirect_uri, client_id, secret_sealed, auth_method FROM index_client "
            "WHERE client_id = ?",
            client_id,
        )
        return self._registration_of(row, row["server"], row["redirect_uri"]) if row else None

    def _registration_of(self, row: dict, server: str, redirect_uri: str) -> Registration:
        sealed = row["secret_sealed"]
        context = f"index-client\n{server}\n{redirect_uri}"
        return Registration(
            row["client_id"], self._box.open(sealed, context) if sealed else None, row["auth_method"]
        )

    async def keep_registration(self, server: str, redirect_uri: str, registration: Registration) -> bool:
        """Whether this call stored it; a registration another call stored first stands."""
        secret = registration.secret
        sealed = self._box.seal(secret, f"index-client\n{server}\n{redirect_uri}") if secret else None
        changed = await self._db.execute(
            "INSERT INTO index_client (server, redirect_uri, client_id, secret_sealed, auth_method, "
            "registered_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (server, redirect_uri) DO NOTHING",
            server,
            redirect_uri,
            registration.client_id,
            sealed,
            registration.auth_method,
            self._clock.now(),
        )
        return changed == 1

    async def connection(self, owner: str) -> Connection | None:
        row = await self._db.row("SELECT * FROM index_connection WHERE owner = ?", owner)
        if row is None:
            return None
        try:
            access = self._box.open(row["access_sealed"], _context(owner, "access"))
            refresh = (
                self._box.open(row["refresh_sealed"], _context(owner, "refresh"))
                if row["refresh_sealed"]
                else None
            )
        except SealError:
            await self.forget(owner)
            return None
        tokens = Tokens(access, refresh, row["expires_at"], row["scope"])
        return Connection(owner, tokens, row["client_id"], row["version"], tuple(json.loads(row["linked"])))

    async def keep(self, owner: str, tokens: Tokens, client_id: str) -> None:
        """A new connection, or a reconnection: the tokens are replaced and what was linked stays."""
        now = self._clock.now()
        await self._db.execute(
            "INSERT INTO index_connection (owner, access_sealed, refresh_sealed, expires_at, scope, "
            "client_id, "
            "version, linked, connected_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, '[]', ?, ?) "
            "ON CONFLICT (owner) DO UPDATE SET access_sealed = excluded.access_sealed, "
            "refresh_sealed = excluded.refresh_sealed, expires_at = excluded.expires_at, "
            "scope = excluded.scope, client_id = excluded.client_id, version = version + 1, "
            "updated_at = excluded.updated_at",
            owner,
            *self._sealed(owner, tokens),
            tokens.expires_at,
            tokens.scope,
            client_id,
            now,
            now,
        )

    def _sealed(self, owner: str, tokens: Tokens) -> tuple[str, str | None]:
        refresh = self._box.seal(tokens.refresh, _context(owner, "refresh")) if tokens.refresh else None
        return self._box.seal(tokens.access, _context(owner, "access")), refresh

    async def claim_refresh(self, connection: Connection) -> bool:
        """Whether this call may refresh now: one at a time per connection, since a refresh token is good
        once. A claim a crashed call left is open to the next after half a minute."""
        now = self._clock.now()
        changed = await self._db.execute(
            "UPDATE index_connection SET refreshing_at = ? WHERE owner = ? AND version = ? "
            "AND (refreshing_at IS NULL OR refreshing_at <= ?)",
            now,
            connection.owner,
            connection.version,
            now - REFRESH_CLAIM_MS,
        )
        return changed == 1

    async def release_refresh(self, connection: Connection) -> None:
        await self._db.execute(
            "UPDATE index_connection SET refreshing_at = NULL WHERE owner = ? AND version = ?",
            connection.owner,
            connection.version,
        )

    async def swap(self, connection: Connection, tokens: Tokens) -> bool:
        """Replaces the tokens only while the row is still the version they were read at, so of two calls that
        refreshed together one wins."""
        kept = replace(tokens, refresh=tokens.refresh or connection.tokens.refresh)
        access, refresh = self._sealed(connection.owner, kept)
        changed = await self._db.execute(
            "UPDATE index_connection SET access_sealed = ?, refresh_sealed = ?, expires_at = ?, scope = ?, "
            "version = version + 1, refreshing_at = NULL, updated_at = ? WHERE owner = ? AND version = ?",
            access,
            refresh,
            kept.expires_at,
            kept.scope,
            self._clock.now(),
            connection.owner,
            connection.version,
        )
        return changed == 1

    async def link(self, owner: str, merchant: str) -> None:
        await self._db.execute(
            "UPDATE index_connection SET linked = CASE WHEN EXISTS (SELECT 1 FROM json_each(linked) "
            "WHERE value = ?) THEN linked ELSE json_insert(linked, '$[#]', ?) END, updated_at = ? "
            "WHERE owner = ?",
            merchant,
            merchant,
            self._clock.now(),
            owner,
        )

    async def unlink(self, owner: str, merchant: str) -> None:
        """Index no longer treats this merchant as linked, so 234 stops treating it so."""
        await self._db.execute(
            "UPDATE index_connection SET linked = (SELECT COALESCE(json_group_array(value), '[]') "
            "FROM json_each(linked) WHERE value != ?), updated_at = ? WHERE owner = ?",
            merchant,
            self._clock.now(),
            owner,
        )

    async def forget(self, owner: str) -> bool:
        return await self._db.execute("DELETE FROM index_connection WHERE owner = ?", owner) == 1
