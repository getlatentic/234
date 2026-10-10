-- A top-up (docs/wallet.md, "Funding"): one Bachs checkout for an amount, made for a signed-in owner's wallet.
-- Each change of state is one UPDATE whose WHERE holds the state it leaves; the money itself moves only as the
-- `fund` entry a genuine webhook writes, keyed by this id (checkout/wallet/topups.py, topup_credit.py).

CREATE TABLE wallet_topup (
  id TEXT PRIMARY KEY CHECK (length(id) = 23 AND id GLOB 'wt-*'),
  owner TEXT NOT NULL REFERENCES wallet (owner),
  amount_kobo INTEGER NOT NULL CHECK (typeof(amount_kobo) = 'integer' AND amount_kobo > 0),
  state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'paid', 'expired')),
  provider_ref TEXT UNIQUE,
  checkout_url TEXT,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  paid_at INTEGER,
  CHECK ((state = 'paid') = (paid_at IS NOT NULL))
);

CREATE INDEX wallet_topup_owner ON wallet_topup (owner, created_at);
CREATE INDEX wallet_topup_open ON wallet_topup (state, expires_at);

CREATE TRIGGER wallet_topup_terms_are_kept
BEFORE UPDATE OF id, owner, amount_kobo, created_at ON wallet_topup
BEGIN
  SELECT RAISE(ABORT, 'a top-up keeps its owner and amount');
END;

CREATE TRIGGER wallet_topup_paid_is_final
BEFORE UPDATE OF state ON wallet_topup
WHEN OLD.state = 'paid' AND NEW.state <> 'paid'
BEGIN
  SELECT RAISE(ABORT, 'a paid top-up stays paid');
END;
