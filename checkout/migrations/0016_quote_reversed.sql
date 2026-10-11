-- A delivered order its provider took back (docs/wallet.md, "Reversals"): VTpass can reverse airtime or data
-- after reporting it delivered, and a quote it reverses ends `reversed`, its wallet payment refunded in the
-- same batch (checkout/flows/reversal.py). A settled quote may only become reversed, and a reversed one stays.
--
-- SQLite cannot change a CHECK, so `quotes` is rebuilt with every row kept. `quote_events` refers to it, so it
-- is set aside first and rebuilt after, which leaves no row pointing at a table being dropped; the indexes and
-- triggers go with the old table and are made again here, `quote_finished` telling `reversed` too.

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
     'reversed')),
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

CREATE TRIGGER quote_finished
AFTER UPDATE OF state ON quotes
WHEN NEW.state <> OLD.state
  AND NEW.state IN ('settled', 'failed', 'abandoned', 'declined', 'unavailable', 'refund_due', 'expired',
                    'reversed')
BEGIN
  INSERT OR IGNORE INTO event_outbox (event_id, subscription_id, data, occurred_at)
  SELECT 'evt_' || NEW.id || '_' || NEW.state, s.id,
    json_object('quote_id', NEW.id, 'connector', NEW.connector, 'state', NEW.state,
                'amount_kobo', NEW.amount_kobo, 'description', NEW.description),
    COALESCE(NEW.settled_at, NEW.expires_at)
  FROM event_subscriptions s
  WHERE s.owner = NEW.owner AND s.connector = NEW.connector AND (s.quote_id IS NULL OR s.quote_id = NEW.id);
END;

-- The simulated VTpass can reverse an order it delivered, from the test routes (testing_routes.py).
ALTER TABLE sim_vtpass ADD COLUMN reversed_at INTEGER;
