-- The wallet (docs/wallet.md): one row per signed-in owner, and an append-only journal whose signed sum is the
-- balance. There is no balance column: every rule that reads the balance sums the journal in the same
-- statement that writes to it (checkout/wallet/journal.py).

CREATE TABLE wallet (
  owner TEXT PRIMARY KEY CHECK (length(owner) = 32 AND owner NOT GLOB '*[^0-9a-f]*'),
  frozen INTEGER NOT NULL DEFAULT 0 CHECK (frozen IN (0, 1)),
  created_at INTEGER NOT NULL
);

CREATE TABLE wallet_entry (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  owner TEXT NOT NULL REFERENCES wallet (owner),
  kind TEXT NOT NULL CHECK (kind IN ('fund', 'spend', 'release', 'refund', 'withdraw', 'withdraw_back', 'adjust')),
  sign INTEGER NOT NULL CHECK (
    (kind IN ('spend', 'withdraw') AND sign = -1)
    OR (kind IN ('fund', 'release', 'refund', 'withdraw_back') AND sign = 1)
    OR (kind = 'adjust' AND sign IN (-1, 1))
  ),
  amount_kobo INTEGER NOT NULL CHECK (typeof(amount_kobo) = 'integer' AND amount_kobo > 0),
  ref TEXT NOT NULL CHECK (length(ref) > 0),
  quote_id TEXT,
  created_at INTEGER NOT NULL,
  UNIQUE (owner, kind, ref)
);

CREATE INDEX wallet_entry_owner ON wallet_entry (owner, seq);

CREATE TRIGGER wallet_entries_are_kept
BEFORE UPDATE ON wallet_entry
BEGIN
  SELECT RAISE(ABORT, 'a wallet entry cannot be changed');
END;

CREATE TRIGGER wallet_entries_are_not_removed
BEFORE DELETE ON wallet_entry
BEGIN
  SELECT RAISE(ABORT, 'a wallet entry cannot be removed');
END;
