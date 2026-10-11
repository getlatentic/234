# SPDX-License-Identifier: AGPL-3.0-or-later
"""Migration 0016 on a ledger that already holds quotes and their events, as the deployed one does: every row
stays, the guards on quotes still hold, and a settled quote may now become reversed and nothing else."""

import pytest

from checkout.sqlite_db import SqliteDb, all_migrations

REVERSAL_MIGRATION = "0016_quote_reversed.sql"
INSERT = (
    "INSERT INTO quotes (id, owner, payer_group, connector, kind, amount_kobo, currency, description,"
    " merchant, details, progress, state, idempotency_key, request_hash, created_at, expires_at, approved_at,"
    " settled_at) VALUES (?, ?, '', 'airtime', 'airtime', 50000, 'NGN', 'MTN airtime', 'MTN', '{}', '{}',"
    " ?, ?, 'h', 1, 2, ?, ?)"
)
QUOTES = [
    ("qt-00000000000000000001", "settled", 5, 6),
    ("qt-00000000000000000002", "refund_due", 5, 7),
    ("qt-00000000000000000003", "open", None, None),
]


@pytest.fixture
def migrated() -> SqliteDb:
    ordered = all_migrations()
    at = next(i for i, m in enumerate(ordered) if m.name == REVERSAL_MIGRATION)
    db = SqliteDb(ordered[:at])
    for quote_id, state, approved, settled in QUOTES:
        db.connection.execute(INSERT, (quote_id, "a1" * 16, state, f"key-{quote_id}", approved, settled))
        db.connection.execute(
            "INSERT INTO quote_events (quote_id, event, seq, at) VALUES (?, 'approval.claimed', 1, 5)",
            (quote_id,),
        )
    for migration in ordered[at:]:
        db.migrate(migration)
    return db


async def test_every_quote_and_event_stays(migrated):
    rows = await migrated.rows("SELECT id, state, approved_at, settled_at FROM quotes ORDER BY id")
    assert [(r["id"], r["state"], r["approved_at"], r["settled_at"]) for r in rows] == QUOTES
    assert len(await migrated.rows("SELECT * FROM quote_events")) == 3


async def test_the_indexes_and_triggers_are_made_again(migrated):
    names = {
        r["name"] for r in await migrated.rows("SELECT name FROM sqlite_master WHERE tbl_name = 'quotes'")
    }
    assert {
        "quotes_approved_at",
        "quotes_owner_approved_at",
        "quotes_group_approved_at",
        "quotes_are_fixed",
        "quotes_delivered_stay_delivered",
        "quote_finished",
    } <= names
    with pytest.raises(Exception, match="cannot be changed"):
        await migrated.execute("UPDATE quotes SET amount_kobo = 1 WHERE id = 'qt-00000000000000000001'")


async def test_a_settled_quote_becomes_reversed_and_nothing_else(migrated):
    with pytest.raises(Exception, match="only be reversed"):
        await migrated.execute("UPDATE quotes SET state = 'failed' WHERE id = 'qt-00000000000000000001'")
    await migrated.execute("UPDATE quotes SET state = 'reversed' WHERE id = 'qt-00000000000000000001'")
    with pytest.raises(Exception, match="only be reversed"):
        await migrated.execute("UPDATE quotes SET state = 'settled' WHERE id = 'qt-00000000000000000001'")


async def test_an_event_still_names_a_quote_that_exists(migrated):
    with pytest.raises(Exception, match="FOREIGN KEY"):
        await migrated.execute(
            "INSERT INTO quote_events (quote_id, event, seq, at) VALUES ('qt-x', 'e', 1, 1)"
        )
