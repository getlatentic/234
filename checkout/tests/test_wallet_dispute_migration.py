# SPDX-License-Identifier: AGPL-3.0-or-later
"""Migration 0015 on a wallet that already has entries, as the deployed one does: the journal is rebuilt for
the dispute kinds with every row and seq kept, numbering goes on after them, and the rebuilt journal is as
append-only as before. The dispute's own rows keep their terms, and a decided dispute stays decided."""

import sqlite3

import pytest

from checkout.sqlite_db import SqliteDb, all_migrations
from tests.support import ALICE, BOB, START

DISPUTE_MIGRATION = "0015_wallet_dispute.sql"
ENTRY = (
    "INSERT INTO wallet_entry (id, owner, kind, sign, amount_kobo, ref, quote_id, created_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)
OLD = [
    ("we-1", ALICE, "fund", 1, 500_000, "wt-a", None, START),
    ("we-2", BOB, "fund", 1, 100_000, "wt-b", None, START),
    ("we-3", ALICE, "spend", -1, 50_000, "qt-1", "qt-1", START + 1),
    ("we-4", ALICE, "release", 1, 50_000, "qt-1", "qt-1", START + 2),
    ("we-5", ALICE, "withdraw", -1, 200_000, "wd-1", None, START + 3),
]


def before_and_after() -> tuple[list, list]:
    ordered = all_migrations()
    at = next(i for i, m in enumerate(ordered) if m.name == DISPUTE_MIGRATION)
    return ordered[:at], ordered[at:]


@pytest.fixture
def db() -> SqliteDb:
    """A journal with entries (and an ops-frozen wallet) before the migration, then migrated."""
    before, after = before_and_after()
    database = SqliteDb(before)
    for owner in (ALICE, BOB):
        database.connection.execute(
            "INSERT INTO wallet (owner, frozen, created_at) VALUES (?, 0, ?)", (owner, START)
        )
    for row in OLD:
        database.connection.execute(ENTRY, row)
    with pytest.raises(sqlite3.IntegrityError):
        database.connection.execute(ENTRY, ("we-6", ALICE, "spend", 1, 1, "qt-x", None, START))
    database.connection.execute("UPDATE wallet SET frozen = 1 WHERE owner = ?", (BOB,))
    for migration in after:
        database.migrate(migration)
    return database


def rows(db: SqliteDb, sql: str, *params) -> list[tuple]:
    return [tuple(row) for row in db.connection.execute(sql, params).fetchall()]


def test_every_entry_and_its_seq_survive_the_rebuild(db):
    kept = rows(
        db,
        "SELECT id, owner, kind, sign, amount_kobo, ref, quote_id, created_at FROM wallet_entry ORDER BY seq",
    )
    assert kept == OLD
    assert [seq for (seq,) in rows(db, "SELECT seq FROM wallet_entry ORDER BY seq")] == [1, 2, 3, 4, 5]


def test_numbering_goes_on_after_the_kept_entries(db):
    db.connection.execute(ENTRY, ("we-7", ALICE, "dispute", -1, 100_000, "dsp_1", None, START + 9))
    db.connection.execute(ENTRY, ("we-8", ALICE, "dispute_back", 1, 100_000, "dsp_1", None, START + 10))
    assert rows(db, "SELECT seq, kind FROM wallet_entry WHERE seq > 5 ORDER BY seq") == [
        (6, "dispute"),
        (7, "dispute_back"),
    ]


def test_the_rebuilt_journal_still_refuses_changes_and_removals(db):
    with pytest.raises(sqlite3.IntegrityError, match="cannot be changed"):
        db.connection.execute("UPDATE wallet_entry SET amount_kobo = 1 WHERE id = 'we-1'")
    with pytest.raises(sqlite3.IntegrityError, match="cannot be removed"):
        db.connection.execute("DELETE FROM wallet_entry WHERE id = 'we-1'")


@pytest.mark.parametrize(
    "row",
    [
        ("we-9", ALICE, "dispute", 1, 1, "dsp_x", None, START),
        ("we-9", ALICE, "dispute_back", -1, 1, "dsp_x", None, START),
        ("we-9", ALICE, "chargeback", -1, 1, "dsp_x", None, START),
        ("we-9", ALICE, "fund", 1, 500_000, "wt-a", None, START),
    ],
)
def test_the_rebuilt_journal_keeps_each_kinds_sign_and_one_entry_per_ref(db, row):
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(ENTRY, row)


def test_the_index_the_balance_reads_by_is_made_again(db):
    assert rows(
        db,
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'wallet_entry' "
        "AND sql IS NOT NULL",
    ) == [("wallet_entry_owner",)]
    assert rows(db, "SELECT name FROM sqlite_master WHERE name = 'wallet_entry_next'") == []


def test_the_wallet_frozen_by_operations_is_still_frozen(db):
    assert rows(db, "SELECT owner, frozen FROM wallet ORDER BY owner") == [(ALICE, 0), (BOB, 1)]


DISPUTE = (
    "INSERT INTO wallet_dispute (id, owner, topup_id, charge_id, amount_kobo, state, created_at) "
    "VALUES ('dsp_1', ?, 'wt-0000000000000000000a', 'ch_1', 100000, 'open', ?)"
)
TOPUP = (
    "INSERT INTO wallet_topup (id, owner, amount_kobo, state, charge_id, created_at, expires_at, paid_at) "
    "VALUES ('wt-0000000000000000000a', ?, 100000, 'paid', 'ch_1', ?, ?, ?)"
)


@pytest.fixture
def opened(db) -> SqliteDb:
    db.connection.execute(TOPUP, (ALICE, START, START + 1, START))
    db.connection.execute(DISPUTE, (ALICE, START))
    return db


def test_a_top_up_keeps_its_charge(opened):
    with pytest.raises(sqlite3.IntegrityError, match="keeps its charge"):
        opened.connection.execute("UPDATE wallet_topup SET charge_id = 'ch_2'")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        opened.connection.execute(TOPUP.replace("000a", "000b"), (ALICE, START, START + 1, START))


def test_a_dispute_keeps_its_terms(opened):
    with pytest.raises(sqlite3.IntegrityError, match="keeps its top-up and amount"):
        opened.connection.execute("UPDATE wallet_dispute SET amount_kobo = 1")


def test_a_decided_dispute_stays_decided(opened):
    opened.connection.execute(
        "UPDATE wallet_dispute SET state = 'lost', decided_at = 1, written_off_kobo = 5"
    )
    for change in ("state = 'won', written_off_kobo = 0", "written_off_kobo = 0", "decided_at = 2"):
        with pytest.raises(sqlite3.IntegrityError, match="stays decided"):
            opened.connection.execute(f"UPDATE wallet_dispute SET {change}")


@pytest.mark.parametrize(
    "change",
    [
        "state = 'won', decided_at = 1, written_off_kobo = 5",
        "state = 'lost', decided_at = 1, written_off_kobo = 100001",
        "state = 'lost'",
        "decided_at = 1",
    ],
)
def test_a_dispute_is_decided_with_its_time_and_a_write_off_only_when_lost(opened, change):
    with pytest.raises(sqlite3.IntegrityError):
        opened.connection.execute(f"UPDATE wallet_dispute SET {change}")
