-- A withdrawal (docs/wallet.md, "Withdrawing"): money from a person's wallet to a Nigerian bank account, as a
-- Paystack transfer whose reference is this id. The money moves only as the `withdraw` entry (taken when the
-- person presses Withdraw) and, when the transfer fails or comes back, the `withdraw_back` entry, both keyed by
-- this id (checkout/wallet/withdrawals.py, withdrawal_outcome.py).
--
-- open: the account is resolved, waiting for the person to confirm its name and press Withdraw; nothing taken.
-- sent: the money is taken and the transfer is sent or being sent; Paystack has not settled it (undecided).
-- succeeded | failed | reversed: what Paystack said; failed and reversed give the money back.
-- expired: open past its time; nothing was ever taken.

CREATE TABLE wallet_withdrawal (
  id TEXT PRIMARY KEY CHECK (length(id) = 23 AND id GLOB 'wd-*'),
  owner TEXT NOT NULL REFERENCES wallet (owner),
  amount_kobo INTEGER NOT NULL CHECK (typeof(amount_kobo) = 'integer' AND amount_kobo > 0),
  bank_code TEXT NOT NULL CHECK (length(bank_code) > 0),
  bank_name TEXT,
  account_number TEXT NOT NULL CHECK (length(account_number) = 10 AND account_number NOT GLOB '*[^0-9]*'),
  account_name TEXT NOT NULL CHECK (length(account_name) > 0),
  recipient_code TEXT NOT NULL CHECK (length(recipient_code) > 0),
  state TEXT NOT NULL DEFAULT 'open'
    CHECK (state IN ('open', 'expired', 'sent', 'succeeded', 'failed', 'reversed')),
  transfer_code TEXT,
  transfer_status TEXT,
  sending_since INTEGER,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  name_confirmed_at INTEGER,
  decided_at INTEGER,
  CHECK ((state IN ('open', 'expired')) = (name_confirmed_at IS NULL)),
  CHECK ((state IN ('succeeded', 'failed', 'reversed')) = (decided_at IS NOT NULL))
);

CREATE INDEX wallet_withdrawal_owner ON wallet_withdrawal (owner, created_at);
CREATE INDEX wallet_withdrawal_state ON wallet_withdrawal (state, expires_at);

CREATE TRIGGER wallet_withdrawal_terms_are_kept
BEFORE UPDATE OF id, owner, amount_kobo, bank_code, account_number, account_name, recipient_code, created_at
ON wallet_withdrawal
BEGIN
  SELECT RAISE(ABORT, 'a withdrawal keeps its owner, amount and account');
END;

CREATE TRIGGER wallet_withdrawal_final_is_final
BEFORE UPDATE OF state ON wallet_withdrawal
WHEN OLD.state <> NEW.state AND (
  OLD.state IN ('expired', 'failed', 'reversed')
  OR (OLD.state = 'succeeded' AND NEW.state <> 'reversed')
)
BEGIN
  SELECT RAISE(ABORT, 'a decided withdrawal stays decided');
END;

-- Withdrawals are blocked for an owner while any row here is not lifted: a dispute on one of their top-ups
-- holds one (getlatentic/planning#641). Spending inside 234 is not blocked.
CREATE TABLE wallet_withdrawal_block (
  owner TEXT NOT NULL REFERENCES wallet (owner),
  reason TEXT NOT NULL CHECK (length(reason) > 0),
  ref TEXT NOT NULL CHECK (length(ref) > 0),
  created_at INTEGER NOT NULL,
  lifted_at INTEGER,
  PRIMARY KEY (owner, reason, ref)
);
