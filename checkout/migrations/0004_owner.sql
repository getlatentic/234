-- Every quote belongs to one owner: the opaque key the chat host sends with each tool call (a visitor's
-- id). The daily limit, lookups, approvals and receipts are scoped by it, so one visitor's spending never
-- reaches another's allowance.
--
-- ALTER TABLE ADD COLUMN is the one change D1 applies to a table with rows in it. Quotes made before this
-- migration take the owner 'legacy', which no caller can present (a key is 32 hex characters), so they
-- count towards nobody's day and can be read by nobody.
ALTER TABLE quotes ADD COLUMN owner TEXT NOT NULL DEFAULT 'legacy';

-- The daily sum: one owner's approved spend since the start of the day.
CREATE INDEX quotes_owner_approved_at ON quotes (owner, approved_at);

-- An owner never changes: the fixed columns of 0001 with `owner` added.
DROP TRIGGER quotes_are_fixed;
CREATE TRIGGER quotes_are_fixed
BEFORE UPDATE OF connector, kind, amount_kobo, currency, description, merchant, merchant_ref,
  details, idempotency_key, request_hash, created_at, expires_at, owner ON quotes
BEGIN
  SELECT RAISE(ABORT, 'a quote cannot be changed after it is made');
END;
