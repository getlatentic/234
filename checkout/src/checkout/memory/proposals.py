# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a card asks the person to decide, and the only code that writes an entry.

`remember` and `update` make a proposal and write nothing. The person's Save on the card calls `apply`, whose
statement reads the validated content from the proposal row itself and writes it only while the proposal is
pending, unexpired and the owner's, and only while the owner has room. The card's token is a keyed digest of
the owner and the proposal id: the card is given it in `_meta`, and the model never is."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from ..clock import Clock
from ..db import Db
from ..ids import new_memory_id
from .settings import MemorySettings

REMEMBER, UPDATE, FORGET = "remember", "update", "forget"
PENDING, APPLIED, DISCARDED, UNDONE = "pending", "applied", "discarded", "undone"
_FIELDS = "title, hook, body, bank_code, account_number, account_name"
_NEW_ROW = (
    "INSERT INTO memory_entry (id, owner, kind, title, hook, body, source, bank_code, account_number, "
    "account_name, verified_at, created_at, updated_at, last_used) "
    "SELECT p.id, p.owner, json_extract(p.payload, '$.kind'), json_extract(p.payload, '$.title'), "
    "json_extract(p.payload, '$.hook'), json_extract(p.payload, '$.body'), "
    "json_extract(p.payload, '$.source'), "
    "json_extract(p.payload, '$.bank_code'), json_extract(p.payload, '$.account_number'), "
    "json_extract(p.payload, '$.account_name'), "
    "CASE WHEN json_extract(p.payload, '$.kind') = 'recipient' THEN ? END, ?, ?, ? "
    "FROM memory_proposal p WHERE p.id = ? AND p.owner = ? AND p.op = 'remember' AND p.state = 'pending' "
    "AND p.expires_at > ? "
    "AND (SELECT COUNT(*) FROM memory_entry WHERE owner = p.owner AND deleted_at IS NULL) < ?"
)
_CHANGED_ROW = (
    "UPDATE memory_entry SET "
    "title = (SELECT json_extract(payload, '$.title') FROM memory_proposal WHERE id = ?), "
    "hook = (SELECT json_extract(payload, '$.hook') FROM memory_proposal WHERE id = ?), "
    "body = (SELECT json_extract(payload, '$.body') FROM memory_proposal WHERE id = ?), "
    "bank_code = (SELECT json_extract(payload, '$.bank_code') FROM memory_proposal WHERE id = ?), "
    "account_number = (SELECT json_extract(payload, '$.account_number') FROM memory_proposal WHERE id = ?), "
    "account_name = (SELECT json_extract(payload, '$.account_name') FROM memory_proposal WHERE id = ?), "
    "verified_at = CASE WHEN kind = 'recipient' THEN ? END, updated_at = ? "
    "WHERE id = (SELECT target_id FROM memory_proposal WHERE id = ?) AND owner = ? AND deleted_at IS NULL "
    "AND EXISTS (SELECT 1 FROM memory_proposal WHERE id = ? AND owner = ? AND op = 'update' "
    "AND state = 'pending' AND expires_at > ?)"
)
_DECIDED = (
    "UPDATE memory_proposal SET state = ?, decided_at = ? WHERE id = ? AND owner = ? AND state = ? "
    "AND changes() > 0"
)


@dataclass(frozen=True)
class Proposal:
    id: str
    owner: str
    op: str
    target_id: str | None
    payload: dict[str, Any]
    state: str
    created_at: int
    expires_at: int
    decided_at: int | None

    @classmethod
    def of(cls, row: dict[str, Any]) -> Proposal:
        return cls(**{**{k: row[k] for k in cls.__dataclass_fields__}, "payload": json.loads(row["payload"])})

    def expired(self, now: int) -> bool:
        return self.state == PENDING and self.expires_at <= now


def confirm_token(secret: bytes, owner: str, proposal_id: str) -> str:
    return hmac.new(secret, f"memory:{owner}:{proposal_id}".encode(), hashlib.sha256).hexdigest()


class Proposals:
    def __init__(self, db: Db, clock: Clock, settings: MemorySettings, secret: str) -> None:
        self._db, self._clock, self._settings = db, clock, settings
        self._secret = secret.encode()

    def token(self, owner: str, proposal_id: str) -> str:
        return confirm_token(self._secret, owner, proposal_id)

    def token_is_valid(self, owner: str, proposal_id: str, given: str) -> bool:
        return hmac.compare_digest(self.token(owner, proposal_id), given)

    async def get(self, owner: str, proposal_id: str) -> Proposal | None:
        row = await self._db.row(
            "SELECT * FROM memory_proposal WHERE id = ? AND owner = ?", proposal_id, owner
        )
        return Proposal.of(row) if row else None

    async def create(
        self, owner: str, op: str, target_id: str | None, payload: dict[str, Any], state: str = PENDING
    ) -> Proposal:
        """A new proposal. An owner who leaves more than `max_pending` unanswered has the oldest of them
        discarded, so a model that proposes in a loop cannot pile up work."""
        now = self._clock.now()
        if state == PENDING:
            await self._make_room(owner, now)
        ttl = self._settings.retention_ms if op == FORGET else self._settings.proposal_ttl_seconds * 1000
        proposal_id = new_memory_id()
        await self._db.execute(
            "INSERT INTO memory_proposal (id, owner, op, target_id, payload, state, created_at, expires_at, "
            "decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            proposal_id, owner, op, target_id, json.dumps(payload, ensure_ascii=False), state, now, now + ttl,
            None if state == PENDING else now,
        )  # fmt: skip
        created = await self.get(owner, proposal_id)
        assert created is not None
        return created

    async def _make_room(self, owner: str, now: int) -> None:
        await self._db.execute(
            "UPDATE memory_proposal SET state = 'discarded', decided_at = ? WHERE id IN ("
            "SELECT id FROM memory_proposal WHERE owner = ? AND state = 'pending' "
            "ORDER BY created_at DESC, rowid DESC "
            "LIMIT -1 OFFSET ?)",
            now,
            owner,
            self._settings.max_pending - 1,
        )

    async def apply(self, owner: str, proposal: Proposal) -> bool:
        """Writes what the person confirmed, once. False when nothing was written: the proposal was not
        pending, had expired, or the owner has no room."""
        now = self._clock.now()
        pid = proposal.id
        if proposal.op == REMEMBER:
            effect = (
                _NEW_ROW,
                (now, now, now, now, pid, owner, now, self._settings.max_entries),
            )
        else:
            effect = (_CHANGED_ROW, (pid, pid, pid, pid, pid, pid, now, now, pid, owner, pid, owner, now))
        answers = await self._db.batch([effect, (_DECIDED, (APPLIED, now, pid, owner, PENDING))])
        return answers[1].changes == 1

    async def discard(self, owner: str, proposal_id: str) -> bool:
        return (
            await self._db.execute(
                "UPDATE memory_proposal SET state = 'discarded', decided_at = ? WHERE id = ? AND owner = ? "
                "AND state = 'pending'",
                self._clock.now(),
                proposal_id,
                owner,
            )
            == 1
        )

    async def undo_forget(self, owner: str, proposal: Proposal) -> bool:
        """Brings back an entry the person forgot, while the retention period lasts and the owner has room."""
        now = self._clock.now()
        restore = (
            "UPDATE memory_entry SET deleted_at = NULL, updated_at = ? WHERE id = ? AND owner = ? "
            "AND deleted_at IS NOT NULL AND deleted_at > ? "
            "AND (SELECT COUNT(*) FROM memory_entry WHERE owner = ? AND deleted_at IS NULL) < ?"
        )
        mark = (
            "UPDATE memory_proposal SET state = 'undone', decided_at = ? WHERE id = ? AND owner = ? "
            "AND op = 'forget' AND state = 'applied' AND changes() > 0"
        )
        answers = await self._db.batch(
            [
                (
                    restore,
                    (
                        now,
                        proposal.target_id,
                        owner,
                        now - self._settings.retention_ms,
                        owner,
                        self._settings.max_entries,
                    ),
                ),
                (mark, (now, proposal.id, owner)),
            ]
        )
        return answers[1].changes == 1
