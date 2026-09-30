-- A quote can be approved, put back when the provider never took the request, and approved again. The
-- event key gains a sequence number so each approval cycle records its own claim, and "one claim per
-- cycle" is still enforced by the primary key.
DROP TABLE quote_events;
CREATE TABLE quote_events (
  quote_id TEXT NOT NULL REFERENCES quotes (id),
  event TEXT NOT NULL,
  seq INTEGER NOT NULL DEFAULT 1,
  at INTEGER NOT NULL,
  PRIMARY KEY (quote_id, event, seq)
);
