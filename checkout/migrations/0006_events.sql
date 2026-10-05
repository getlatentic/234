-- MCP events (src/checkout/events): who asked to hear when a quote ends, and the outbox of what to send them.
--
-- A subscription belongs to one owner and one connector, and follows one quote or (quote_id NULL) every quote.
-- Its id is derived from the owner, the event, the arguments and the callback URL, so subscribing again
-- refreshes it. The secret signs what is sent (Standard Webhooks); it is the subscriber's, given for that.
CREATE TABLE event_subscriptions (
  id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  connector TEXT NOT NULL,
  name TEXT NOT NULL,
  quote_id TEXT,
  arguments TEXT NOT NULL,
  url TEXT NOT NULL,
  secret TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE INDEX event_subscriptions_owner ON event_subscriptions (owner, connector);

-- One row per event and subscription; done_at is set once it was delivered, refused for good, or given up on.
CREATE TABLE event_outbox (
  event_id TEXT NOT NULL,
  subscription_id TEXT NOT NULL,
  data TEXT NOT NULL,
  occurred_at INTEGER NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_at INTEGER NOT NULL DEFAULT 0,
  done_at INTEGER,
  PRIMARY KEY (event_id, subscription_id)
);

CREATE INDEX event_outbox_due ON event_outbox (done_at, next_at);

-- Every path that ends a quote is an UPDATE of its state, so the event is written here, in the same
-- statement, for each subscription of that owner and connector that follows it.
CREATE TRIGGER quote_finished
AFTER UPDATE OF state ON quotes
WHEN NEW.state <> OLD.state
  AND NEW.state IN ('settled', 'failed', 'abandoned', 'declined', 'unavailable', 'refund_due', 'expired')
BEGIN
  INSERT OR IGNORE INTO event_outbox (event_id, subscription_id, data, occurred_at)
  SELECT 'evt_' || NEW.id || '_' || NEW.state, s.id,
    json_object('quote_id', NEW.id, 'connector', NEW.connector, 'state', NEW.state,
                'amount_kobo', NEW.amount_kobo, 'description', NEW.description),
    COALESCE(NEW.settled_at, NEW.expires_at)
  FROM event_subscriptions s
  WHERE s.owner = NEW.owner AND s.connector = NEW.connector AND (s.quote_id IS NULL OR s.quote_id = NEW.id);
END;
