# SPDX-License-Identifier: AGPL-3.0-or-later
"""Quotes, the spend they reserve, and the rules that keep both honest.

D1 has no interactive transactions, so no rule here reads and then writes. Each is a
constraint in the schema or one conditional UPDATE whose WHERE clause holds the rule, and the
number of rows it changed says whether this caller won:

* one approval per quote: `state = 'open'` in the UPDATE's WHERE;
* the daily limit, per owner: the SUM of that owner's approved spend today is a subquery of that same
  UPDATE, so the check and the reservation are one atomic statement and two approvals cannot both fit;
  another owner's spend is not in the sum, and another owner's quote is not in the WHERE;
* idempotency: UNIQUE (connector, idempotency_key), the key stored with its owner in front so two owners
  never meet on one key; the loser of the insert reads the winner;
* progress: `json_patch` merges in SQL, so two writers touching different keys both land.

Every statement names the owner of the call (owner.py). A quote of another owner is not found, exactly as
one that does not exist, so a guessed quote id shows nothing. A batch is one D1 transaction; the approval and
its event row travel in one.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any

from .amount_floor import assert_above_floor
from .clock import Clock, lagos_day_start
from .db import Db, UniqueViolation
from .errors import DomainError
from .ids import new_quote_id
from .money import Kobo, format_naira
from .owner import current_group, current_owner

SPENDING_STATES = ("approved", "settled", "refund_due")
ENDED_STATES = ("settled", "failed", "abandoned", "declined", "unavailable", "refund_due")
_SPENDING_SQL = ", ".join(f"'{s}'" for s in SPENDING_STATES)


@dataclass(frozen=True)
class Limits:
    per_payment_kobo: Kobo
    daily_kobo: Kobo
    group_daily_kobo: Kobo = 50_000_000
    """What all the owners of one payer group may approve together in a day (owner.py)."""


@dataclass(frozen=True)
class ClaimTerms:
    """What a funding source adds to the one approval of a quote: progress written by the same UPDATE, and
    a condition on the quote row (`quotes`) that must hold in its WHERE."""

    progress: dict[str, Any]
    condition: str


@dataclass(frozen=True)
class Budget:
    per_payment_kobo: Kobo
    daily_kobo: Kobo
    spent_today_kobo: Kobo

    @property
    def remaining_today_kobo(self) -> Kobo:
        return max(self.daily_kobo - self.spent_today_kobo, 0)


@dataclass(frozen=True)
class CheckoutFacts:
    merchant: str
    description: str
    state: str


@dataclass(frozen=True)
class NewQuote:
    connector: str
    kind: str
    amount_kobo: Kobo
    description: str
    merchant: str
    merchant_ref: str | None
    details: dict[str, Any]
    idempotency_key: str
    request_hash: str


@dataclass(frozen=True)
class Quote:
    id: str
    connector: str
    kind: str
    amount_kobo: Kobo
    description: str
    merchant: str
    merchant_ref: str | None
    details: dict[str, Any]
    progress: dict[str, Any]
    state: str
    created_at: int
    expires_at: int
    approved_at: int | None
    settled_at: int | None
    request_hash: str = field(default="", repr=False)


def quote_of(row: dict[str, Any]) -> Quote:
    return Quote(
        id=row["id"],
        connector=row["connector"],
        kind=row["kind"],
        amount_kobo=row["amount_kobo"],
        description=row["description"],
        merchant=row["merchant"],
        merchant_ref=row["merchant_ref"],
        details=json.loads(row["details"]),
        progress=json.loads(row["progress"]),
        state=row["state"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        approved_at=row["approved_at"],
        settled_at=row["settled_at"],
        request_hash=row["request_hash"],
    )


def request_hash(**fields: Any) -> str:
    canonical = json.dumps(sorted(fields.items()), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class Ledger:
    def __init__(
        self,
        db: Db,
        clock: Clock,
        limits: Limits,
        quote_ttl_seconds: int,
        approval_secret: str,
        default_owner: str | None,
    ) -> None:
        """`default_owner` acts for a call that names none (local development and tests); None refuses it."""
        self._db = db
        self._clock = clock
        self.limits = limits
        self._ttl_ms = quote_ttl_seconds * 1000
        self._secret = approval_secret.encode()
        self._default_owner = default_owner

    def owner(self) -> str:
        owner = current_owner() or self._default_owner
        if owner is None:
            raise DomainError("OWNER_REQUIRED", "This call does not say whose it is, so nothing was done.")
        return owner

    async def _group_spent(self, group: str) -> Kobo:
        row = await self._db.row(
            f"SELECT COALESCE(SUM(amount_kobo), 0) AS spent FROM quotes "
            f"WHERE payer_group = ? AND approved_at >= ? AND state IN ({_SPENDING_SQL})",
            group,
            lagos_day_start(self._clock.now()),
        )
        return int(row["spent"])

    async def _assert_within_group(self, amount: Kobo, group: str) -> None:
        if group and await self._group_spent(group) + amount > self.limits.group_daily_kobo:
            raise DomainError(
                "LIMIT_GROUP_DAILY",
                f"{format_naira(amount)} would take what the people of this agent approved today above "
                f"{format_naira(self.limits.group_daily_kobo)}, "
                "the most one agent's people can spend in a day.",
            )

    def _scoped_key(self, key: str) -> str:
        """The idempotency key as stored: UNIQUE (connector, idempotency_key) spans every owner, so the
        owner goes in front and two owners never share a key."""
        return f"{self.owner()}:{key}"

    async def _expire_if_due(self, row: dict[str, Any]) -> dict[str, Any]:
        if row["state"] != "open" or self._clock.now() < row["expires_at"]:
            return row
        await self._db.execute(
            "UPDATE quotes SET state = 'expired' WHERE id = ? AND owner = ? AND state = 'open'",
            row["id"],
            row["owner"],
        )
        return await self._row(row["id"], row["owner"]) or row

    async def _row(self, quote_id: str, owner: str) -> dict[str, Any] | None:
        return await self._db.row("SELECT * FROM quotes WHERE id = ? AND owner = ?", quote_id, owner)

    async def get(self, quote_id: str) -> Quote | None:
        row = await self._row(quote_id, self.owner())
        return quote_of(await self._expire_if_due(row)) if row else None

    async def checkout_facts(self, quote_id: str) -> CheckoutFacts | None:
        """What the simulated checkout page shows for a quote, and the state its buttons need. The page is
        opened by holding an unguessable reference, not as an owner: this is the one read naming none."""
        row = await self._db.row("SELECT merchant, description, state FROM quotes WHERE id = ?", quote_id)
        return CheckoutFacts(row["merchant"], row["description"], row["state"]) if row else None

    async def require(self, quote_id: str, connector: str) -> Quote:
        quote = await self.get(quote_id)
        if quote is None:
            raise DomainError("QUOTE_NOT_FOUND", f"There is no quote {quote_id}.")
        if quote.connector != connector:
            raise DomainError(
                "WRONG_CONNECTOR",
                f"Quote {quote_id} belongs to the {quote.connector} connector, not {connector}.",
            )
        return quote

    async def budget(self) -> Budget:
        row = await self._db.row(
            f"SELECT COALESCE(SUM(amount_kobo), 0) AS spent FROM quotes "
            f"WHERE owner = ? AND approved_at >= ? AND state IN ({_SPENDING_SQL})",
            self.owner(),
            lagos_day_start(self._clock.now()),
        )
        return Budget(self.limits.per_payment_kobo, self.limits.daily_kobo, int(row["spent"]))

    def _assert_within_per_payment(self, amount: Kobo) -> None:
        if amount > self.limits.per_payment_kobo:
            raise DomainError(
                "LIMIT_PER_PAYMENT",
                f"{format_naira(amount)} is above the per-payment limit of "
                f"{format_naira(self.limits.per_payment_kobo)}.",
            )

    def _assert_within_daily(self, amount: Kobo, spent: Kobo) -> None:
        if spent + amount > self.limits.daily_kobo:
            left = max(self.limits.daily_kobo - spent, 0)
            raise DomainError(
                "LIMIT_DAILY",
                f"{format_naira(amount)} would take today's approved total above the daily limit "
                f"of {format_naira(self.limits.daily_kobo)} ({format_naira(left)} left today).",
            )

    async def assert_quotable(self, amount: Kobo) -> None:
        """Refuses an amount the floor or the limits do not allow, so no provider is called for it."""
        assert_above_floor(amount)
        self._assert_within_per_payment(amount)
        self._assert_within_daily(amount, (await self.budget()).spent_today_kobo)
        await self._assert_within_group(amount, current_group())

    async def replay(self, connector: str, key: str, digest: str) -> Quote | None:
        """The quote an earlier request with this key made; a key reused for another request is refused."""
        row = await self._db.row(
            "SELECT * FROM quotes WHERE owner = ? AND connector = ? AND idempotency_key = ?",
            self.owner(),
            connector,
            self._scoped_key(key),
        )
        if row is None:
            return None
        if row["request_hash"] != digest:
            raise DomainError(
                "IDEMPOTENCY_CONFLICT",
                "That idempotency_key was already used for a different request. "
                "Use a new key for a new request.",
            )
        return quote_of(await self._expire_if_due(row))

    async def create(self, new: NewQuote) -> tuple[Quote, bool]:
        """Returns the quote and whether it is a replay of an earlier identical request."""
        replayed = await self.replay(new.connector, new.idempotency_key, new.request_hash)
        if replayed:
            return replayed, True
        await self.assert_quotable(new.amount_kobo)
        quote_id, now = new_quote_id(), self._clock.now()
        try:
            await self._db.execute(
                "INSERT INTO quotes (id, owner, payer_group, connector, kind, amount_kobo, currency,"
                " description, merchant, merchant_ref, details, progress, state, idempotency_key,"
                " request_hash, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'NGN', ?, ?, ?, ?, '{}', 'open', ?, ?, ?, ?)",
                quote_id,
                self.owner(),
                current_group(),
                new.connector,
                new.kind,
                new.amount_kobo,
                new.description,
                new.merchant,
                new.merchant_ref,
                json.dumps(new.details),
                self._scoped_key(new.idempotency_key),
                new.request_hash,
                now,
                now + self._ttl_ms,
            )
        except UniqueViolation:
            winner = await self.replay(new.connector, new.idempotency_key, new.request_hash)
            if winner is None:
                raise
            return winner, True
        return await self._must_get(quote_id), False

    async def _group_of(self, quote_id: str) -> str:
        row = await self._db.row("SELECT payer_group FROM quotes WHERE id = ?", quote_id)
        return row["payer_group"] if row else ""

    async def _must_get(self, quote_id: str) -> Quote:
        quote = await self.get(quote_id)
        if quote is None:
            raise RuntimeError(f"quote {quote_id} vanished")
        return quote

    async def claim_approval(
        self, quote_id: str, connector: str, terms: ClaimTerms | None = None
    ) -> tuple[Quote, bool]:
        """The one approval a quote can have. A later claim finds the first and changes nothing.

        The UPDATE holds every rule: the caller's own quote, still open, not expired, within the
        per-payment limit, the caller's approved spend today plus this quote within the daily limit,
        and, for a quote made in a payer group, the group's approved spend today plus this quote within
        the group's limit, and the funding source's `terms`. The event row rides in the same batch,
        inserted only when the UPDATE changed a row.
        """
        now, owner = self._clock.now(), self.owner()
        funded = terms or ClaimTerms({}, "1")
        results = await self._db.batch(
            [
                (
                    "UPDATE quotes SET state = 'approved', approved_at = ?, "
                    "progress = json_patch(progress, ?) "
                    "WHERE id = ? AND owner = ? AND connector = ? AND state = 'open' AND expires_at > ? "
                    "AND amount_kobo <= ? AND amount_kobo + (SELECT COALESCE(SUM(amount_kobo), 0) "
                    f"FROM quotes WHERE owner = ? AND approved_at >= ? AND state IN ({_SPENDING_SQL})) <= ? "
                    "AND (payer_group = '' OR amount_kobo + (SELECT COALESCE(SUM(g.amount_kobo), 0) "
                    "FROM quotes AS g WHERE g.payer_group = quotes.payer_group AND g.approved_at >= ? "
                    f"AND g.state IN ({_SPENDING_SQL})) <= ?) AND ({funded.condition})",
                    (
                        now,
                        json.dumps(funded.progress),
                        quote_id,
                        owner,
                        connector,
                        now,
                        self.limits.per_payment_kobo,
                        owner,
                        lagos_day_start(now),
                        self.limits.daily_kobo,
                        lagos_day_start(now),
                        self.limits.group_daily_kobo,
                    ),
                ),
                (
                    "INSERT INTO quote_events (quote_id, event, seq, at) "
                    "SELECT ?, 'approval.claimed', 1 + (SELECT COUNT(*) FROM quote_events "
                    "WHERE quote_id = ? AND event = 'approval.released'), ? WHERE changes() = 1",
                    (quote_id, quote_id, now),
                ),
            ]
        )
        if results[0].changes == 1:
            return await self._must_get(quote_id), True
        return await self._why_not_approved(quote_id, connector)

    async def _why_not_approved(self, quote_id: str, connector: str) -> tuple[Quote, bool]:
        quote = await self.require(quote_id, connector)
        if quote.approved_at is not None:
            return quote, False
        if quote.state == "expired":
            raise DomainError("QUOTE_EXPIRED", "This quote has expired. Ask for a new quote.")
        if quote.state != "open":
            raise DomainError("QUOTE_NOT_OPEN", f"This quote is {quote.state} and cannot be approved.")
        self._assert_within_per_payment(quote.amount_kobo)
        self._assert_within_daily(quote.amount_kobo, (await self.budget()).spent_today_kobo)
        await self._assert_within_group(quote.amount_kobo, await self._group_of(quote_id))
        raise DomainError("APPROVAL_IN_PROGRESS", "The quote changed while it was being approved.")

    async def patch_progress(
        self, quote_id: str, patch: dict[str, Any], only_state: str | None = None
    ) -> Quote:
        """Merges into progress inside SQL (RFC 7396): a None value removes its key. With `only_state`
        the merge happens only while the quote is in that state."""
        await self._db.execute(
            "UPDATE quotes SET progress = json_patch(progress, ?) "
            "WHERE id = ? AND owner = ? AND (? IS NULL OR state = ?)",
            json.dumps(patch),
            quote_id,
            self.owner(),
            only_state,
            only_state,
        )
        return await self._must_get(quote_id)

    async def set_progress_once(self, quote_id: str, key: str, value: Any) -> bool:
        """Writes progress[key] only if it is not set yet; true when this caller wrote it, so of any
        number of racing callers exactly one gets to decide the value."""
        changed = await self._db.execute(
            "UPDATE quotes SET progress = json_patch(progress, json_object(?, json(?))) "
            "WHERE id = ? AND owner = ? AND json_extract(progress, ?) IS NULL",
            key,
            json.dumps(value),
            quote_id,
            self.owner(),
            f"$.{key}",
        )
        return changed == 1

    async def transition(
        self,
        quote_id: str,
        from_states: tuple[str, ...],
        to: str,
        patch: dict[str, Any] | None = None,
    ) -> Quote:
        """Moves a quote between states; asking for the state it is already in is a no-op."""
        marks = ", ".join("?" for _ in from_states)
        ended_at = self._clock.now() if to in ENDED_STATES else None
        changed = await self._db.execute(
            f"UPDATE quotes SET state = ?, settled_at = COALESCE(?, settled_at), "
            f"progress = json_patch(progress, ?) WHERE id = ? AND owner = ? AND state IN ({marks})",
            to,
            ended_at,
            json.dumps(patch or {}),
            quote_id,
            self.owner(),
            *from_states,
        )
        quote = await self._must_get(quote_id)
        if changed == 0 and quote.state != to:
            raise DomainError(
                "QUOTE_NOT_OPEN", f"This quote is {quote.state}, not {' or '.join(from_states)}."
            )
        return quote

    async def release_approval(self, quote_id: str) -> Quote:
        """Puts an approval back when the provider never took the request, and records that it was."""
        await self._db.batch(
            [
                (
                    "UPDATE quotes SET state = 'open', approved_at = NULL WHERE id = ? AND owner = ? "
                    "AND state = 'approved' "
                    "AND json_extract(progress, '$.checkoutUrl') IS NULL",
                    (quote_id, self.owner()),
                ),
                (
                    "INSERT INTO quote_events (quote_id, event, seq, at) "
                    "SELECT ?, 'approval.released', 1 + (SELECT COUNT(*) FROM quote_events "
                    "WHERE quote_id = ? AND event = 'approval.released'), ? WHERE changes() = 1",
                    (quote_id, quote_id, self._clock.now()),
                ),
            ]
        )
        return await self._must_get(quote_id)

    async def acquire_step(
        self, quote_id: str, stale_after_ms: int, patch: dict[str, Any] | None = None
    ) -> bool:
        """True when this caller may talk to a provider now; false while another call is doing so.
        `patch` is merged in the same statement, so the caller's own marker lands with the lock."""
        now = self._clock.now()
        changed = await self._db.execute(
            "UPDATE quotes SET progress = json_patch(json_patch(progress, ?), json_object('inFlightSince', "
            "?)) "
            "WHERE id = ? AND owner = ? AND (json_extract(progress, '$.inFlightSince') IS NULL "
            "OR ? - json_extract(progress, '$.inFlightSince') >= ?)",
            json.dumps(patch or {}),
            now,
            quote_id,
            self.owner(),
            now,
            stale_after_ms,
        )
        return changed == 1

    def approval_token(self, quote_id: str) -> str:
        return hmac.new(self._secret, quote_id.encode(), hashlib.sha256).hexdigest()

    def check_approval_token(self, quote_id: str, token: str) -> bool:
        return hmac.compare_digest(self.approval_token(quote_id), token)
