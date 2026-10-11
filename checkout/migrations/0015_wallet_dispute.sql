-- Disputes on card top-ups (docs/wallet.md, "Disputes"; getlatentic/planning#641). A chargeback names the Bachs
-- charge, so a paid top-up keeps its charge id; the disputed amount is held in the wallet as a `dispute` entry
-- and written back as `dispute_back` when 234 keeps the money (checkout/wallet/disputes.py).

ALTER TABLE wallet_topup ADD COLUMN charge_id TEXT;
CREATE UNIQUE INDEX wallet_topup_charge ON wallet_topup (charge_id) WHERE charge_id IS NOT NULL;

CREATE TRIGGER wallet_topup_charge_is_kept
BEFORE UPDATE OF charge_id ON wallet_topup
WHEN OLD.charge_id IS NOT NULL AND NEW.charge_id IS NOT OLD.charge_id
BEGIN
  SELECT RAISE(ABORT, 'a top-up keeps its charge');
END;

-- SQLite cannot change a CHECK, so the journal is rebuilt with the two dispute kinds: every row is copied with
-- its seq (AUTOINCREMENT then continues after the highest), and the index and both triggers are made again. A
-- DROP TABLE fires no DELETE trigger, and nothing refers to wallet_entry, so the copy and the drop go through.
CREATE TABLE wallet_entry_next (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  owner TEXT NOT NULL REFERENCES wallet (owner),
  kind TEXT NOT NULL CHECK (kind IN (
    'fund', 'spend', 'release', 'refund', 'withdraw', 'withdraw_back', 'dispute', 'dispute_back', 'adjust'
  )),
  sign INTEGER NOT NULL CHECK (
    (kind IN ('spend', 'withdraw', 'dispute') AND sign = -1)
    OR (kind IN ('fund', 'release', 'refund', 'withdraw_back', 'dispute_back') AND sign = 1)
    OR (kind = 'adjust' AND sign IN (-1, 1))
  ),
  amount_kobo INTEGER NOT NULL CHECK (typeof(amount_kobo) = 'integer' AND amount_kobo > 0),
  ref TEXT NOT NULL CHECK (length(ref) > 0),
  quote_id TEXT,
  created_at INTEGER NOT NULL,
  UNIQUE (owner, kind, ref)
);

INSERT INTO wallet_entry_next (seq, id, owner, kind, sign, amount_kobo, ref, quote_id, created_at)
SELECT seq, id, owner, kind, sign, amount_kobo, ref, quote_id, created_at FROM wallet_entry ORDER BY seq;

DROP TABLE wallet_entry;
ALTER TABLE wallet_entry_next RENAME TO wallet_entry;

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

-- A wallet is frozen while `wallet.frozen` is set (by operations) or any row here is not lifted. Each freeze is
-- lifted on its own, so ending a dispute never unfreezes a wallet frozen for something else
-- (checkout/wallet/freeze.py).
CREATE TABLE wallet_freeze (
  owner TEXT NOT NULL REFERENCES wallet (owner),
  reason TEXT NOT NULL CHECK (length(reason) > 0),
  ref TEXT NOT NULL CHECK (length(ref) > 0),
  created_at INTEGER NOT NULL,
  lifted_at INTEGER,
  PRIMARY KEY (owner, reason, ref)
);

-- open: the money is held (what the wallet had, up to the disputed amount), withdrawals are blocked, and the
-- wallet is frozen if the hold fell short. won | closed: the hold went back. lost | prevented: the customer
-- has the money; what the hold could not cover is 234's loss, `written_off_kobo`, for the reconciliation.
CREATE TABLE wallet_dispute (
  id TEXT PRIMARY KEY CHECK (length(id) > 0),
  owner TEXT NOT NULL REFERENCES wallet (owner),
  topup_id TEXT NOT NULL REFERENCES wallet_topup (id),
  charge_id TEXT NOT NULL CHECK (length(charge_id) > 0),
  amount_kobo INTEGER NOT NULL CHECK (typeof(amount_kobo) = 'integer' AND amount_kobo > 0),
  state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'won', 'lost', 'closed', 'prevented')),
  written_off_kobo INTEGER NOT NULL DEFAULT 0
    CHECK (typeof(written_off_kobo) = 'integer' AND written_off_kobo BETWEEN 0 AND amount_kobo),
  created_at INTEGER NOT NULL,
  decided_at INTEGER,
  CHECK ((state = 'open') = (decided_at IS NULL)),
  CHECK (state IN ('lost', 'prevented') OR written_off_kobo = 0)
);

CREATE INDEX wallet_dispute_owner ON wallet_dispute (owner, created_at);
CREATE INDEX wallet_dispute_state ON wallet_dispute (state, decided_at);

CREATE TRIGGER wallet_dispute_terms_are_kept
BEFORE UPDATE OF id, owner, topup_id, charge_id, amount_kobo, created_at ON wallet_dispute
BEGIN
  SELECT RAISE(ABORT, 'a dispute keeps its top-up and amount');
END;

CREATE TRIGGER wallet_dispute_decided_is_final
BEFORE UPDATE ON wallet_dispute
WHEN OLD.state <> 'open'
BEGIN
  SELECT RAISE(ABORT, 'a decided dispute stays decided');
END;
