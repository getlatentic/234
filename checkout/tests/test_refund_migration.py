# SPDX-License-Identifier: AGPL-3.0-or-later
"""Migration 0019 on a ledger that already holds quotes and their events, as the deployed one does: every row
stays, the guards on quotes still hold, and a quote owing a refund may now end refunded, only once Paystack
processed it."""

import pytest

from checkout.sqlite_db import SqliteDb, all_migrations

REFUND_MIGRATION = "0019_quote_refund.sql"
INSERT = (
    "INSERT INTO quotes (id, owner, payer_group, connector, kind, amount_kobo, currency, description,"
    " merchant, details, progress, state, idempotency_key, request_hash, created_at, expires_at, approved_at,"
    " settled_at) VALUES (?, ?, '', 'airtime', 'airtime', 50000, 'NGN', 'MTN airtime', 'MTN', '{}', '{}',"
    " ?, ?, 'h', 1, 2, ?, ?)"
)
QUOTES = [
    ("qt-00000000000000000001", "settled", 5, 6),
    ("qt-00000000000000000002", "refund_due", 5, 7),
    ("qt-00000000000000000003", "reversed", 5, 8),
    ("qt-00000000000000000004", "open", None, None),
]
OWED = "qt-00000000000000000002"


@pytest.fixture
def migrated() -> SqliteDb:
    ordered = all_migrations()
    at = next(i for i, m in enumerate(ordered) if m.name == REFUND_MIGRATION)
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


async def _refund(db: SqliteDb, state: str) -> None:
    await db.execute(
        "INSERT INTO quote_refund (quote_id, owner, amount_kobo, transaction_reference, transaction_id, "
        "state, created_at, decided_at) VALUES (?, ?, 50000, 'qt-00000000000000000002-a1', 9, ?, 1, ?)",
        OWED,
        "a1" * 16,
        state,
        None if state == "sent" else 2,
    )


async def test_every_quote_and_event_stays(migrated):
    rows = await migrated.rows("SELECT id, state, approved_at, settled_at FROM quotes ORDER BY id")
    assert [(r["id"], r["state"], r["approved_at"], r["settled_at"]) for r in rows] == QUOTES
    assert len(await migrated.rows("SELECT * FROM quote_events")) == 4


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
        "quotes_refunded_once_paid_back",
        "quote_finished",
    } <= names
    with pytest.raises(Exception, match="cannot be changed"):
        await migrated.execute("UPDATE quotes SET amount_kobo = 1 WHERE id = 'qt-00000000000000000001'")
    with pytest.raises(Exception, match="only be reversed"):
        await migrated.execute("UPDATE quotes SET state = 'failed' WHERE id = 'qt-00000000000000000003'")


async def test_an_owed_quote_ends_refunded_only_once_its_refund_is_processed(migrated):
    await _refund(migrated, "sent")
    with pytest.raises(Exception, match="refunded only once"):
        await migrated.execute("UPDATE quotes SET state = 'refunded' WHERE id = ?", OWED)
    await migrated.execute("UPDATE quote_refund SET state = 'processed', decided_at = 3")
    assert await migrated.execute("UPDATE quotes SET state = 'refunded' WHERE id = ?", OWED) == 1


async def test_a_refund_is_decided_exactly_when_it_has_a_decision(migrated):
    with pytest.raises(Exception, match="CHECK"):
        await migrated.execute(
            "INSERT INTO quote_refund (quote_id, owner, amount_kobo, transaction_reference, transaction_id, "
            "state, created_at) VALUES (?, 'o', 50000, 'r', 9, 'processed', 1)",
            OWED,
        )
