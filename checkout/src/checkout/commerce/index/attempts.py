# SPDX-License-Identifier: AGPL-3.0-or-later
"""A connection being made, shown on a card (the card's id is the attempt's). Signing in at Index is armed
with a `state` and a PKCE verifier: the state goes to Index and comes back once on the redirect, and what
is kept is its SHA-256 with the verifier sealed. A state is taken once, for the owner the attempt belongs
to, while the attempt is open and unexpired: a state presented twice, by another person, late, or not at
all is not taken, and a state that does not match changes nothing."""

import hashlib
import secrets
from dataclasses import dataclass

from ...clock import Clock
from ...db import Db
from .secretbox import SealError, SecretBox

TTL_MS = 10 * 60_000
MAX_TRIES = 6
"""How many phones and codes one attempt may send to Index, so a card cannot be used to spam a phone."""


@dataclass(frozen=True)
class Attempt:
    id: str
    owner: str
    merchant_id: str | None
    """The Index merchant (`index:chowdeck`) the person is connecting for, if one."""
    step: str
    status: str
    expires_at: int


@dataclass(frozen=True)
class Armed:
    state: str
    verifier: str


def new_attempt_id() -> str:
    return f"cn-{secrets.token_hex(10)}"


def state_hash(state: str) -> str:
    return hashlib.sha256(f"234-index-state\n{state}".encode()).hexdigest()


def _attempt_of(row: dict) -> Attempt:
    return Attempt(row["id"], row["owner"], row["merchant_id"], row["step"], row["status"], row["expires_at"])


def _context(attempt_id: str) -> str:
    return f"index-attempt\n{attempt_id}"


class Attempts:
    def __init__(self, db: Db, clock: Clock, box: SecretBox) -> None:
        self._db, self._clock, self._box = db, clock, box

    async def start(self, owner: str, merchant_id: str | None) -> Attempt:
        attempt_id, now = new_attempt_id(), self._clock.now()
        await self._db.execute(
            "INSERT INTO index_attempt (id, owner, merchant_id, step, status, expires_at, created_at, "
            "updated_at) VALUES (?, ?, ?, 'authorize', 'open', ?, ?, ?)",
            attempt_id,
            owner,
            merchant_id,
            now + TTL_MS,
            now,
            now,
        )
        return Attempt(attempt_id, owner, merchant_id, "authorize", "open", now + TTL_MS)

    async def get(self, owner: str, attempt_id: str) -> Attempt | None:
        row = await self._db.row("SELECT * FROM index_attempt WHERE id = ? AND owner = ?", attempt_id, owner)
        return _attempt_of(row) if row else None

    async def arm(self, owner: str, attempt_id: str) -> Armed | None:
        """A new state and verifier for an attempt of this owner that is to sign in or is being tried again,
        and a fresh time to do it in; None for an attempt that is not this owner's or has ended."""
        armed = Armed(secrets.token_urlsafe(32), secrets.token_urlsafe(48))
        now = self._clock.now()
        changed = await self._db.execute(
            "UPDATE index_attempt SET state_hash = ?, verifier_sealed = ?, status = 'open', "
            "step = 'authorize', tries = 0, expires_at = ?, updated_at = ? "
            "WHERE id = ? AND owner = ? AND status != 'ended'",
            state_hash(armed.state),
            self._box.seal(armed.verifier, _context(attempt_id)),
            now + TTL_MS,
            now,
            attempt_id,
            owner,
        )
        return armed if changed == 1 else None

    async def take(self, owner: str, state: str) -> tuple[Attempt, str] | None:
        """The attempt this owner armed with `state` and its verifier, taken once: the first call to reach
        the statement that clears the state gets it."""
        now = self._clock.now()
        row = await self._db.row(
            "SELECT * FROM index_attempt WHERE state_hash = ? AND owner = ? AND status = 'open' "
            "AND step = 'authorize' AND expires_at > ?",
            state_hash(state),
            owner,
            now,
        )
        if row is None:
            return None
        taken = await self._db.execute(
            "UPDATE index_attempt SET state_hash = NULL, verifier_sealed = NULL, updated_at = ? "
            "WHERE id = ? AND state_hash = ?",
            now,
            row["id"],
            state_hash(state),
        )
        if taken != 1:
            return None
        try:
            return _attempt_of(row), self._box.open(row["verifier_sealed"], _context(row["id"]))
        except SealError:
            return None

    async def advance(self, owner: str, attempt_id: str, step: str) -> None:
        await self._db.execute(
            "UPDATE index_attempt SET step = ?, updated_at = ? WHERE id = ? AND owner = ? "
            "AND status = 'open'",
            step,
            self._clock.now(),
            attempt_id,
            owner,
        )

    async def mark(self, owner: str, attempt_id: str, status: str) -> None:
        """Ends the attempt as `denied`, `expired` or `ended`, and forgets what it held."""
        await self._db.execute(
            "UPDATE index_attempt SET status = ?, state_hash = NULL, verifier_sealed = NULL, updated_at = ? "
            "WHERE id = ? AND owner = ?",
            status,
            self._clock.now(),
            attempt_id,
            owner,
        )

    async def count_try(self, owner: str, attempt_id: str) -> bool:
        """Whether this attempt may send one more phone or code to Index; counted in the same statement."""
        changed = await self._db.execute(
            "UPDATE index_attempt SET tries = tries + 1, updated_at = ? WHERE id = ? AND owner = ? "
            "AND status = 'open' AND tries < ?",
            self._clock.now(),
            attempt_id,
            owner,
            MAX_TRIES,
        )
        return changed == 1

    async def end_all(self, owner: str) -> None:
        """The person disconnected: no attempt of theirs can finish a connection they ended."""
        await self._db.execute(
            "UPDATE index_attempt SET status = 'ended', state_hash = NULL, verifier_sealed = NULL, "
            "updated_at = ? WHERE owner = ? AND status = 'open'",
            self._clock.now(),
            owner,
        )
