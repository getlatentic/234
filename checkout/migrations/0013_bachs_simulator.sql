-- What the simulated Bachs remembers (checkout/bachs/sim_store.py): the checkouts it made, so every Worker
-- instance sees the same ones. A reference is unique for good, as Bachs keeps it, and the request's hash
-- answers a repeated Idempotency-Key with the same checkout or refuses one sent with another body.

CREATE TABLE sim_bachs_checkouts (
  checkout_id TEXT PRIMARY KEY,
  reference TEXT NOT NULL UNIQUE,
  idempotency_key TEXT UNIQUE,
  request_hash TEXT NOT NULL,
  amount TEXT NOT NULL,
  currency TEXT NOT NULL,
  email TEXT,
  metadata TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('open', 'paid')),
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  paid_at INTEGER
);
