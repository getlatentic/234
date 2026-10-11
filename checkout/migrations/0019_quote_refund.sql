-- A Paystack refund of a quote paid at the checkout (docs/wallet.md, "Refunds"): a quote whose order failed after
-- it was paid (`refund_due`), or that its provider reversed after delivery (`reversed`), gives the payer its
-- whole amount back through Paystack's Refund API, once, keyed by the quote (checkout/refunds/). A quote paid
-- from the wallet is refunded to the wallet instead and never has a row here.
--
-- sent: 234 took the send and sends the refund, or sent it, and Paystack has not finished it (undecided).
-- needs_attention: Paystack needs the payer's bank account to finish it (`refund.needs-attention`); undecided.
-- processed | failed: what Paystack said. A failed refund is 234's to follow up.
-- refused: Paystack holds no payment of exactly this quote's amount to refund, so nothing was sent.
--
-- A refund_due quote whose refund is processed ends `refunded`, and no longer counts against the day's limits;
-- a reversed quote stays reversed. SQLite cannot change a CHECK, so `quotes` is rebuilt as 0016 rebuilt it,
-- with every row, index and trigger kept, `quote_finished` telling `refunded` too.

CREATE TABLE quotes_new (
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
    ('open', 'approved', 'settled', 'failed', 'abandoned', 'expired', 'declined', 'unavailable', 'refund_due',
     'reversed', 'refunded')),
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  approved_at INTEGER,
  settled_at INTEGER,
  owner TEXT NOT NULL DEFAULT 'legacy',
  payer_group TEXT NOT NULL DEFAULT '',
  UNIQUE (connector, idempotency_key)
);

INSERT INTO quotes_new (id, connector, kind, amount_kobo, currency, description, merchant, merchant_ref, details,
  progress, state, idempotency_key, request_hash, created_at, expires_at, approved_at, settled_at, owner,
  payer_group)
SELECT id, connector, kind, amount_kobo, currency, description, merchant, merchant_ref, details, progress, state,
  idempotency_key, request_hash, created_at, expires_at, approved_at, settled_at, owner, payer_group
FROM quotes;

CREATE TABLE quote_events_kept AS SELECT quote_id, event, seq, at FROM quote_events;
DROP TABLE quote_events;
DROP TABLE quotes;
ALTER TABLE quotes_new RENAME TO quotes;

CREATE TABLE quote_events (
  quote_id TEXT NOT NULL REFERENCES quotes (id),
  event TEXT NOT NULL,
  seq INTEGER NOT NULL DEFAULT 1,
  at INTEGER NOT NULL,
  PRIMARY KEY (quote_id, event, seq)
);
INSERT INTO quote_events (quote_id, event, seq, at) SELECT quote_id, event, seq, at FROM quote_events_kept;
DROP TABLE quote_events_kept;

CREATE INDEX quotes_approved_at ON quotes (approved_at);
CREATE INDEX quotes_owner_approved_at ON quotes (owner, approved_at);
CREATE INDEX quotes_group_approved_at ON quotes (payer_group, approved_at);

CREATE TRIGGER quotes_are_fixed
BEFORE UPDATE OF connector, kind, amount_kobo, currency, description, merchant, merchant_ref,
  details, idempotency_key, request_hash, created_at, expires_at, owner, payer_group ON quotes
BEGIN
  SELECT RAISE(ABORT, 'a quote cannot be changed after it is made');
END;

CREATE TRIGGER quotes_delivered_stay_delivered
BEFORE UPDATE OF state ON quotes
WHEN OLD.state <> NEW.state AND (OLD.state = 'reversed' OR (OLD.state = 'settled' AND NEW.state <> 'reversed'))
BEGIN
  SELECT RAISE(ABORT, 'a delivered quote can only be reversed');
END;

CREATE TRIGGER quotes_refunded_once_paid_back
BEFORE UPDATE OF state ON quotes
WHEN OLD.state <> NEW.state AND (OLD.state = 'refunded' OR (NEW.state = 'refunded' AND (OLD.state <> 'refund_due'
  OR NOT EXISTS (SELECT 1 FROM quote_refund AS r WHERE r.quote_id = NEW.id AND r.state = 'processed'))))
BEGIN
  SELECT RAISE(ABORT, 'a quote is refunded only once Paystack processed its refund, and stays refunded');
END;

CREATE TRIGGER quote_finished
AFTER UPDATE OF state ON quotes
WHEN NEW.state <> OLD.state
  AND NEW.state IN ('settled', 'failed', 'abandoned', 'declined', 'unavailable', 'refund_due', 'expired',
                    'reversed', 'refunded')
BEGIN
  INSERT OR IGNORE INTO event_outbox (event_id, subscription_id, data, occurred_at)
  SELECT 'evt_' || NEW.id || '_' || NEW.state, s.id,
    json_object('quote_id', NEW.id, 'connector', NEW.connector, 'state', NEW.state,
                'amount_kobo', NEW.amount_kobo, 'description', NEW.description),
    COALESCE(NEW.settled_at, NEW.expires_at)
  FROM event_subscriptions s
  WHERE s.owner = NEW.owner AND s.connector = NEW.connector AND (s.quote_id IS NULL OR s.quote_id = NEW.id);
END;

CREATE TABLE quote_refund (
  quote_id TEXT PRIMARY KEY REFERENCES quotes (id),
  owner TEXT NOT NULL,
  amount_kobo INTEGER NOT NULL CHECK (typeof(amount_kobo) = 'integer' AND amount_kobo > 0),
  transaction_reference TEXT NOT NULL CHECK (length(transaction_reference) > 0),
  transaction_id INTEGER CHECK (transaction_id IS NULL OR typeof(transaction_id) = 'integer'),
  state TEXT NOT NULL CHECK (state IN ('sent', 'needs_attention', 'processed', 'failed', 'refused')),
  refund_id INTEGER,
  refund_status TEXT,
  why TEXT,
  sending_since INTEGER,
  created_at INTEGER NOT NULL,
  decided_at INTEGER,
  CHECK ((state IN ('processed', 'failed', 'refused')) = (decided_at IS NOT NULL)),
  CHECK (state = 'refused' OR transaction_id IS NOT NULL),
  CHECK (state <> 'refused' OR refund_id IS NULL)
);

CREATE INDEX quote_refund_state ON quote_refund (state, created_at);

CREATE TRIGGER quote_refund_terms_are_kept
BEFORE UPDATE OF quote_id, owner, amount_kobo, transaction_reference, transaction_id, created_at ON quote_refund
BEGIN
  SELECT RAISE(ABORT, 'a refund keeps its quote, amount and transaction');
END;

CREATE TRIGGER quote_refund_keeps_paystacks_refund
BEFORE UPDATE OF refund_id ON quote_refund
WHEN OLD.refund_id IS NOT NULL AND NEW.refund_id IS NOT OLD.refund_id
BEGIN
  SELECT RAISE(ABORT, 'a refund keeps the Paystack refund it was given');
END;

CREATE TRIGGER quote_refund_decided_stays_decided
BEFORE UPDATE OF state ON quote_refund
WHEN OLD.state <> NEW.state AND OLD.state IN ('processed', 'failed', 'refused')
BEGIN
  SELECT RAISE(ABORT, 'a decided refund stays decided');
END;

-- The simulated Paystack's refunds, driven to an outcome from the test routes (testing_routes.py).
CREATE TABLE sim_refunds (
  id INTEGER PRIMARY KEY,
  transaction_reference TEXT NOT NULL REFERENCES sim_transactions (reference),
  amount_kobo INTEGER NOT NULL CHECK (amount_kobo > 0),
  currency TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'needs-attention', 'failed', 'processed')),
  merchant_note TEXT,
  customer_note TEXT
);
