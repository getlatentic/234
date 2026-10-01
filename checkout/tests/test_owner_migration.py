# SPDX-License-Identifier: AGPL-3.0-or-later
"""Migration 0004 on a database that already holds quotes, as the deployed ledger does."""

import pytest

from checkout.errors import DomainError
from checkout.ledger import Ledger, Limits
from checkout.owner import acting_for
from checkout.sqlite_db import SqliteDb, all_migrations
from tests.ledger_support import new_quote
from tests.support import ALICE, START, FakeClock

OWNER_MIGRATION = "0004_owner.sql"


def before_and_after() -> tuple[list, list]:
    ordered = all_migrations()
    at = next(i for i, m in enumerate(ordered) if m.name == OWNER_MIGRATION)
    return ordered[:at], ordered[at:]


def old_quote_row(quote_id: str, state: str, key: str, approved_at: int | None) -> tuple:
    created, expires = START - 60_000, START + 600_000
    head = (quote_id, "paystack-pay", "payment", 3_000_000, "NGN", "Lunch", "Demo Kitchen", None)
    return (*head, '{"kind":"payment"}', "{}", state, key, "hash", created, expires, approved_at)


INSERT_OLD = (
    "INSERT INTO quotes (id, connector, kind, amount_kobo, currency, description, merchant, merchant_ref,"
    " details, progress, state, idempotency_key, request_hash, created_at, expires_at, approved_at)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


@pytest.fixture
def migrated():
    """A ledger before the migration with three quotes in it (two approved today, one open), then migrated."""
    before, after = before_and_after()
    db = SqliteDb(before)
    for row in (
        old_quote_row("qt-00000000000000000001", "approved", "old-key-0001", START - 30_000),
        old_quote_row("qt-00000000000000000002", "settled", "old-key-0002", START - 20_000),
        old_quote_row("qt-00000000000000000003", "open", "old-key-0003", None),
    ):
        db.connection.execute(INSERT_OLD, row)
    db.connection.execute(
        "INSERT INTO quote_events (quote_id, event, seq, at) VALUES ('qt-00000000000000000001', 'x', 1, 1)"
    )
    for migration in after:
        db.migrate(migration)
    clock = FakeClock()
    ledger = Ledger(db, clock, Limits(5_000_000, 10_000_000), 600, "secret", None)
    return db, ledger


async def test_the_rows_that_were_there_stay_and_belong_to_no_caller(migrated):
    db, _ = migrated
    rows = await db.rows("SELECT id, owner, state, amount_kobo FROM quotes ORDER BY id")
    assert [(r["owner"], r["state"], r["amount_kobo"]) for r in rows] == [
        ("legacy", "approved", 3_000_000),
        ("legacy", "settled", 3_000_000),
        ("legacy", "open", 3_000_000),
    ]
    assert (await db.row("SELECT COUNT(*) AS n FROM quote_events"))["n"] == 1


async def test_old_spend_counts_towards_nobodys_day_and_old_quotes_are_out_of_reach(migrated):
    _, ledger = migrated
    with acting_for(ALICE):
        assert (await ledger.budget()).spent_today_kobo == 0
        for quote_id in ("qt-00000000000000000001", "qt-00000000000000000003"):
            assert await ledger.get(quote_id) is None
        with pytest.raises(DomainError) as refused:
            await ledger.claim_approval("qt-00000000000000000003", "paystack-pay")
    assert refused.value.code == "QUOTE_NOT_FOUND"


async def test_a_new_quote_may_use_a_key_an_old_quote_used(migrated):
    _, ledger = migrated
    with acting_for(ALICE):
        quote, replayed = await ledger.create(new_quote(250_000, "old-key-0001"))
        assert (await ledger.claim_approval(quote.id, "paystack-pay"))[1] is True
        assert replayed is False


async def test_the_fixed_columns_stay_fixed_and_the_owner_joins_them(migrated):
    db, _ = migrated
    for column, value in (("amount_kobo", 1), ("owner", "'x'"), ("idempotency_key", "'x'")):
        with pytest.raises(Exception, match="cannot be changed"):
            await db.execute(f"UPDATE quotes SET {column} = {value} WHERE id = 'qt-00000000000000000003'")
    await db.execute("UPDATE quotes SET state = 'declined' WHERE id = 'qt-00000000000000000003'")


async def test_the_daily_sum_has_its_index(migrated):
    db, _ = migrated
    plan = await db.rows(
        "EXPLAIN QUERY PLAN SELECT SUM(amount_kobo) FROM quotes WHERE owner = ? AND approved_at >= ?", "a", 1
    )
    assert "quotes_owner_approved_at" in " ".join(str(r["detail"]) for r in plan)


def test_the_migration_adds_a_column_without_rebuilding_the_table():
    migration = next(m for m in all_migrations() if m.name == OWNER_MIGRATION)
    text = migration.read_text()
    assert "ALTER TABLE quotes ADD COLUMN owner TEXT NOT NULL DEFAULT 'legacy'" in text
    assert "DROP TABLE" not in text
