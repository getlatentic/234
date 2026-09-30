-- What the simulated providers remember. Each write that must not race is one statement:
-- an INSERT that a UNIQUE key can refuse, or an UPDATE whose WHERE holds the expected state.

-- The simulated transactions gain a currency, a description and the `ongoing` status (the checkout
-- page is open). They are throwaway state, so the table is rebuilt rather than altered.
DROP TABLE sim_transactions;
CREATE TABLE sim_transactions (
  reference TEXT PRIMARY KEY,
  amount_kobo INTEGER NOT NULL,
  currency TEXT NOT NULL,
  email TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('abandoned', 'ongoing', 'success', 'failed')),
  paid_at TEXT,
  gateway_response TEXT,
  description TEXT NOT NULL
);

CREATE TABLE sim_recipients (
  recipient_code TEXT PRIMARY KEY,
  account_number TEXT NOT NULL,
  bank_code TEXT NOT NULL,
  name TEXT NOT NULL,
  bank_name TEXT NOT NULL,
  UNIQUE (account_number, bank_code)
);

CREATE TABLE sim_transfers (
  reference TEXT PRIMARY KEY,
  transfer_code TEXT NOT NULL UNIQUE,
  recipient_code TEXT NOT NULL REFERENCES sim_recipients (recipient_code),
  amount_kobo INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'otp', 'success', 'failed', 'reversed'))
);

CREATE TABLE sim_vtpass (
  request_id TEXT PRIMARY KEY,
  service_id TEXT NOT NULL,
  phone TEXT NOT NULL,
  amount_naira REAL NOT NULL,
  variation_code TEXT,
  scenario TEXT NOT NULL CHECK (scenario IN ('success', 'pending', 'unexpected', 'no_reply', 'timeout', 'failed')),
  created_at INTEGER NOT NULL
);
