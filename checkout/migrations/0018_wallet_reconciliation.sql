-- The wallet's reconciliation (docs/wallet.md, "Reconciliation"): what 234 owes every wallet, against what it
-- holds at Bachs, Paystack and VTpass, once an hour and whenever an operator asks (checkout/wallet/
-- reconciliation.py). Each run is kept as it was. A provider that could not be read is NULL, never zero, and
-- the run then has no gap: an unknown is not a shortfall. While the latest run with a gap is short, new
-- top-ups are refused (wallet/funding_pause.py).

CREATE TABLE wallet_reconciliation (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  at INTEGER NOT NULL,
  owed_kobo INTEGER NOT NULL CHECK (typeof(owed_kobo) = 'integer'),
  bachs_kobo INTEGER CHECK (bachs_kobo IS NULL OR typeof(bachs_kobo) = 'integer'),
  paystack_kobo INTEGER CHECK (paystack_kobo IS NULL OR typeof(paystack_kobo) = 'integer'),
  vtpass_kobo INTEGER CHECK (vtpass_kobo IS NULL OR typeof(vtpass_kobo) = 'integer'),
  gap_kobo INTEGER,
  withdrawing_kobo INTEGER NOT NULL,
  disputes INTEGER NOT NULL,
  open_disputes INTEGER NOT NULL,
  open_disputed_kobo INTEGER NOT NULL,
  written_off_kobo INTEGER NOT NULL,
  short INTEGER NOT NULL CHECK (short IN (0, 1)),
  CHECK ((gap_kobo IS NULL) = (bachs_kobo IS NULL OR paystack_kobo IS NULL OR vtpass_kobo IS NULL)),
  CHECK (gap_kobo IS NULL OR gap_kobo = owed_kobo - bachs_kobo - paystack_kobo - vtpass_kobo),
  CHECK (short = (gap_kobo IS NOT NULL AND gap_kobo > 0))
);

CREATE TRIGGER wallet_reconciliations_are_kept
BEFORE UPDATE ON wallet_reconciliation
BEGIN
  SELECT RAISE(ABORT, 'a reconciliation is kept as it was');
END;

CREATE TRIGGER wallet_reconciliations_are_not_removed
BEFORE DELETE ON wallet_reconciliation
BEGIN
  SELECT RAISE(ABORT, 'a reconciliation cannot be removed');
END;
