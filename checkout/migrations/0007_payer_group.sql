-- A quote may also belong to a payer group: the host names one for an outside personal agent's chats (its
-- PACT issuer), because every person the agent speaks for is an owner of their own, and an agent could open
-- any number of daily allowances by naming new people. The group's approved spend each day is capped across
-- all its owners. '' is no group.
ALTER TABLE quotes ADD COLUMN payer_group TEXT NOT NULL DEFAULT '';

CREATE INDEX quotes_group_approved_at ON quotes (payer_group, approved_at);

-- A group never changes: the fixed columns of 0004 with `payer_group` added.
DROP TRIGGER quotes_are_fixed;
CREATE TRIGGER quotes_are_fixed
BEFORE UPDATE OF connector, kind, amount_kobo, currency, description, merchant, merchant_ref,
  details, idempotency_key, request_hash, created_at, expires_at, owner, payer_group ON quotes
BEGIN
  SELECT RAISE(ABORT, 'a quote cannot be changed after it is made');
END;
