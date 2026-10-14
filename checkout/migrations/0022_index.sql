-- Paystack Index as a person's own connector (docs/commerce.md, the `index` provider). What 234 keeps for it:
--
-- index_client: the one registration 234 made at Index's authorization server for a redirect address (dynamic
--   client registration, once per deployment). The secret, if Index gave one, is sealed.
-- index_connection: one row per person who connected their Index account. The access and refresh tokens are
--   sealed (checkout/commerce/index/secretbox.py) with a key of the Worker's and the owner's id, so a row
--   copied to another owner opens for nobody. `version` makes a refresh a compare-and-swap, and `refreshing_at` lets one call at a time refresh (a refresh token
--   is good once); `linked` lists the
--   merchants the person linked at Index through 234 (Chowdeck).
-- index_attempt: a connection in progress, shown on a card (its id is the card's id). `state_hash` is the
--   SHA-256 of the `state` sent to Index, which comes back once on the redirect; `verifier_sealed` is the
--   PKCE verifier. Both are removed when the attempt ends.
-- index_catalog: Index's list of merchants, kept for an hour, one row for all people.
-- sim_index_*: the simulated Index (checkout/commerce/index/sim.py) that stands in for Index everywhere
--   except a deployment set to talk to the real one.
--
-- Funding: a quote paid from the person's own Zap carries `funding = 'external'` in its progress, so it never
-- touches the wallet's ledger.
--
-- An account check is no longer tied to a row of `merchant`: an Index merchant is not a row of ours, and a
-- foreign key would refuse its checks. SQLite cannot drop one, so the table is rebuilt with its rows, its index
-- and its trigger.

CREATE TABLE index_client (
  server TEXT NOT NULL,
  redirect_uri TEXT NOT NULL,
  client_id TEXT NOT NULL CHECK (length(client_id) BETWEEN 1 AND 200),
  secret_sealed TEXT,
  auth_method TEXT NOT NULL CHECK (auth_method IN ('none', 'client_secret_post', 'client_secret_basic')),
  registered_at INTEGER NOT NULL,
  PRIMARY KEY (server, redirect_uri)
);

CREATE TABLE index_connection (
  owner TEXT PRIMARY KEY CHECK (length(owner) = 32 AND owner NOT GLOB '*[^0-9a-f]*'),
  access_sealed TEXT NOT NULL,
  refresh_sealed TEXT,
  expires_at INTEGER NOT NULL,
  scope TEXT NOT NULL,
  client_id TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  refreshing_at INTEGER,
  linked TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(linked) AND json_type(linked) = 'array'),
  connected_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE index_attempt (
  id TEXT PRIMARY KEY CHECK (id GLOB 'cn-*' AND length(id) = 23),
  owner TEXT NOT NULL CHECK (length(owner) = 32 AND owner NOT GLOB '*[^0-9a-f]*'),
  merchant_id TEXT,
  step TEXT NOT NULL CHECK (step IN ('authorize', 'phone', 'code', 'done')),
  status TEXT NOT NULL CHECK (status IN ('open', 'denied', 'expired', 'ended')),
  state_hash TEXT,
  verifier_sealed TEXT,
  tries INTEGER NOT NULL DEFAULT 0 CHECK (tries >= 0),
  expires_at INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE UNIQUE INDEX index_attempt_state ON index_attempt (state_hash) WHERE state_hash IS NOT NULL;
CREATE INDEX index_attempt_owner ON index_attempt (owner, created_at);

CREATE TABLE index_catalog (
  scope TEXT PRIMARY KEY,
  body TEXT NOT NULL CHECK (json_valid(body)),
  fetched_at INTEGER NOT NULL
);

CREATE TABLE sim_index_account (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  zap_linked INTEGER NOT NULL DEFAULT 1 CHECK (zap_linked IN (0, 1)),
  zap_kobo INTEGER NOT NULL DEFAULT 0 CHECK (typeof(zap_kobo) = 'integer' AND zap_kobo >= 0),
  chowdeck_linked INTEGER NOT NULL DEFAULT 0 CHECK (chowdeck_linked IN (0, 1)),
  chowdeck_phone TEXT,
  created_at INTEGER NOT NULL
);

CREATE TABLE sim_index_client (
  client_id TEXT PRIMARY KEY,
  secret TEXT,
  redirect_uris TEXT NOT NULL CHECK (json_valid(redirect_uris)),
  created_at INTEGER NOT NULL
);

CREATE TABLE sim_index_grant (
  code TEXT PRIMARY KEY,
  client_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  redirect_uri TEXT NOT NULL,
  challenge TEXT NOT NULL,
  used INTEGER NOT NULL DEFAULT 0 CHECK (used IN (0, 1)),
  expires_at INTEGER NOT NULL
);

CREATE TABLE sim_index_token (
  token TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('access', 'refresh')),
  client_id TEXT NOT NULL,
  account_id TEXT,
  expires_at INTEGER NOT NULL,
  revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1))
);

CREATE TABLE sim_index_call (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id TEXT,
  tool TEXT NOT NULL,
  arguments TEXT NOT NULL,
  confirmed INTEGER NOT NULL CHECK (confirmed IN (0, 1)),
  at INTEGER NOT NULL
);

CREATE TABLE sim_index_order (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  tool TEXT NOT NULL,
  arguments TEXT NOT NULL,
  total_kobo INTEGER NOT NULL,
  status TEXT NOT NULL,
  detail TEXT NOT NULL CHECK (json_valid(detail)),
  created_at INTEGER NOT NULL
);

CREATE TABLE sim_index_setting (
  name TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE account_check_new (
  id TEXT PRIMARY KEY CHECK (length(id) = 23 AND id GLOB 'ck-*'),
  owner TEXT NOT NULL CHECK (length(owner) = 32 AND owner NOT GLOB '*[^0-9a-f]*'),
  merchant_id TEXT NOT NULL CHECK (length(merchant_id) BETWEEN 2 AND 60),
  fields TEXT NOT NULL CHECK (json_valid(fields) AND json_type(fields) = 'object'),
  holder_name TEXT NOT NULL CHECK (length(holder_name) BETWEEN 1 AND 120),
  due_kobo INTEGER CHECK (due_kobo IS NULL OR (typeof(due_kobo) = 'integer' AND due_kobo >= 0)),
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL CHECK (expires_at > created_at)
);

INSERT INTO account_check_new (id, owner, merchant_id, fields, holder_name, due_kobo, created_at, expires_at)
SELECT id, owner, merchant_id, fields, holder_name, due_kobo, created_at, expires_at FROM account_check;

DROP TABLE account_check;
ALTER TABLE account_check_new RENAME TO account_check;

CREATE INDEX account_check_owner ON account_check (owner, merchant_id, created_at);

CREATE TRIGGER account_check_is_kept
BEFORE UPDATE ON account_check
BEGIN
  SELECT RAISE(ABORT, 'an account check cannot be changed');
END;
