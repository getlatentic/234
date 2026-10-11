-- A correction to a wallet (docs/wallet.md, "Corrections"): an `adjust` entry an operator writes through
-- POST /ops/wallet/adjust, keyed by the correction id the operator chose (checkout/wallet/adjustments.py).
--
-- applied: the `adjust` entry exists (ref = this id), written in the same batch that recorded this row.
-- proposed: above the two-operator threshold and nothing moved yet; a second, different operator naming the
-- same id and the same terms applies it.

CREATE TABLE wallet_adjustment (
  correction_id TEXT PRIMARY KEY CHECK (length(correction_id) BETWEEN 1 AND 64),
  owner TEXT NOT NULL REFERENCES wallet (owner),
  sign INTEGER NOT NULL CHECK (sign IN (-1, 1)),
  amount_kobo INTEGER NOT NULL CHECK (typeof(amount_kobo) = 'integer' AND amount_kobo > 0),
  reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 500),
  proposed_by TEXT NOT NULL CHECK (length(proposed_by) BETWEEN 1 AND 64),
  approved_by TEXT CHECK (approved_by IS NULL OR approved_by <> proposed_by),
  state TEXT NOT NULL CHECK (state IN ('proposed', 'applied')),
  created_at INTEGER NOT NULL,
  applied_at INTEGER,
  CHECK ((state = 'applied') = (applied_at IS NOT NULL))
);

CREATE TRIGGER wallet_adjustment_terms_are_kept
BEFORE UPDATE OF correction_id, owner, sign, amount_kobo, reason, proposed_by, created_at ON wallet_adjustment
BEGIN
  SELECT RAISE(ABORT, 'a correction keeps its owner, amount and reason');
END;

CREATE TRIGGER wallet_adjustment_applied_is_final
BEFORE UPDATE OF state ON wallet_adjustment
WHEN OLD.state = 'applied'
BEGIN
  SELECT RAISE(ABORT, 'an applied correction stays applied');
END;

-- The minute's reaper of stale holds reads `spend` entries by age (checkout/wallet/stale_holds.py).
CREATE INDEX wallet_entry_kind ON wallet_entry (kind, created_at);
