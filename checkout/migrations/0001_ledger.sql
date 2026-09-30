-- The ledger. D1 commits every statement on its own, so every rule that must hold under
-- concurrency is either a constraint here or one conditional UPDATE in ledger.py.

CREATE TABLE quotes (
  id TEXT PRIMARY KEY,
  connector TEXT NOT NULL,
  kind TEXT NOT NULL,
  amount_kobo INTEGER NOT NULL CHECK (amount_kobo > 0),
  currency TEXT NOT NULL CHECK (currency = 'NGN'),
  description TEXT NOT NULL,
  merchant TEXT NOT NULL,
  merchant_ref TEXT,
  details TEXT NOT NULL,
  progress TEXT NOT NULL DEFAULT '{}',
  state TEXT NOT NULL CHECK (state IN
    ('open', 'approved', 'settled', 'failed', 'abandoned', 'expired', 'declined', 'unavailable', 'refund_due')),
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  approved_at INTEGER,
  settled_at INTEGER,
  UNIQUE (connector, idempotency_key)
);

CREATE INDEX quotes_approved_at ON quotes (approved_at);

-- A quote cannot change after it is made, even by direct SQL.
CREATE TRIGGER quotes_are_fixed
BEFORE UPDATE OF connector, kind, amount_kobo, currency, description, merchant, merchant_ref,
  details, idempotency_key, request_hash, created_at, expires_at ON quotes
BEGIN
  SELECT RAISE(ABORT, 'a quote cannot be changed after it is made');
END;

-- Append-only facts, one row per (quote, event): the unique key is what makes "approved once" provable.
CREATE TABLE quote_events (
  quote_id TEXT NOT NULL REFERENCES quotes (id),
  event TEXT NOT NULL,
  at INTEGER NOT NULL,
  PRIMARY KEY (quote_id, event)
);

-- The simulated Paystack: transactions the simulator initialised and how they ended.
CREATE TABLE sim_transactions (
  reference TEXT PRIMARY KEY,
  amount_kobo INTEGER NOT NULL,
  email TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('abandoned', 'success', 'failed')),
  paid_at TEXT,
  gateway_response TEXT
);
