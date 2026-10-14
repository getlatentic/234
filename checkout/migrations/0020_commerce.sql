-- The directory of merchants and what they sell (docs/commerce.md, "The words"). A provider is code, not a
-- table: this is the data of the `directory` provider, merchants 234 onboards. A quote made for one keeps a copy
-- of every line, price and fee it was made from (`quotes.details`, fixed by `quotes_are_fixed`), so a later
-- change to an offer never changes what a quote used; what is refused here is a change of who a row is, and
-- the removal of a row a quote names.
--
-- Text in these tables is written by the merchant or by 234. Only `merchant.blurb` is 234's own words on when
-- to choose a merchant; every other text is data the model reads as data (checkout/commerce/text.py).

CREATE TABLE merchant (
  id TEXT PRIMARY KEY CHECK (length(id) BETWEEN 2 AND 40 AND id NOT GLOB '*[^a-z0-9-]*'),
  provider TEXT NOT NULL DEFAULT 'directory' CHECK (length(provider) BETWEEN 1 AND 30 AND provider NOT GLOB '*[^a-z0-9_]*'),
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
  category TEXT NOT NULL CHECK (category IN
    ('food', 'grocery', 'health', 'shop', 'service', 'airtime', 'data', 'tv', 'electricity')),
  status TEXT NOT NULL CHECK (status IN ('live', 'beta', 'coming_soon')),
  requires_link INTEGER NOT NULL DEFAULT 0 CHECK (requires_link IN (0, 1)),
  blurb TEXT NOT NULL CHECK (length(blurb) BETWEEN 1 AND 300),
  min_kobo INTEGER NOT NULL CHECK (typeof(min_kobo) = 'integer' AND min_kobo > 0),
  max_kobo INTEGER NOT NULL CHECK (typeof(max_kobo) = 'integer' AND max_kobo >= min_kobo),
  fee_label TEXT NOT NULL DEFAULT 'Delivery' CHECK (length(fee_label) BETWEEN 1 AND 30),
  fee_kobo INTEGER NOT NULL DEFAULT 0 CHECK (typeof(fee_kobo) = 'integer' AND fee_kobo >= 0),
  checks_account INTEGER NOT NULL DEFAULT 0 CHECK (checks_account IN (0, 1)),
  fields TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(fields) AND json_type(fields) = 'array'),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX merchant_category ON merchant (category, status);

CREATE TABLE offer (
  merchant_id TEXT NOT NULL REFERENCES merchant (id),
  id TEXT NOT NULL CHECK (length(id) BETWEEN 2 AND 60 AND id NOT GLOB '*[^a-z0-9-]*'),
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
  description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 300),
  tags TEXT NOT NULL DEFAULT '' CHECK (length(tags) <= 200),
  price_kind TEXT NOT NULL CHECK (price_kind IN ('fixed', 'range', 'open')),
  price_kobo INTEGER CHECK (price_kobo IS NULL OR (typeof(price_kobo) = 'integer' AND price_kobo > 0)),
  min_kobo INTEGER CHECK (min_kobo IS NULL OR (typeof(min_kobo) = 'integer' AND min_kobo > 0)),
  max_kobo INTEGER CHECK (max_kobo IS NULL OR typeof(max_kobo) = 'integer'),
  available INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0, 1)),
  max_quantity INTEGER NOT NULL DEFAULT 10 CHECK (typeof(max_quantity) = 'integer' AND max_quantity BETWEEN 1 AND 10),
  option_groups TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(option_groups) AND json_type(option_groups) = 'array'),
  position INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (merchant_id, id),
  CHECK (
    (price_kind = 'fixed' AND price_kobo IS NOT NULL AND min_kobo IS NULL AND max_kobo IS NULL)
    OR (price_kind = 'range' AND price_kobo IS NULL AND min_kobo IS NOT NULL AND max_kobo IS NOT NULL
      AND max_kobo >= min_kobo)
    OR (price_kind = 'open' AND price_kobo IS NULL AND min_kobo IS NULL AND max_kobo IS NULL)
  )
);

CREATE TRIGGER merchant_keeps_its_identity
BEFORE UPDATE OF id, provider ON merchant
BEGIN
  SELECT RAISE(ABORT, 'a merchant keeps its id and provider');
END;

CREATE TRIGGER offer_keeps_its_identity
BEFORE UPDATE OF merchant_id, id, price_kind ON offer
BEGIN
  SELECT RAISE(ABORT, 'an offer keeps its merchant, id and kind of price; make a new offer instead');
END;

CREATE TRIGGER merchant_named_by_a_quote_is_kept
BEFORE DELETE ON merchant
WHEN EXISTS (
  SELECT 1 FROM quotes AS q
  WHERE q.connector = 'merchants' AND json_extract(q.details, '$.merchantId') = OLD.id
)
BEGIN
  SELECT RAISE(ABORT, 'a merchant a quote names is retired, not removed');
END;

CREATE TRIGGER offer_named_by_a_quote_is_kept
BEFORE DELETE ON offer
WHEN EXISTS (
  SELECT 1 FROM quotes AS q, json_each(q.details, '$.lines') AS l
  WHERE q.connector = 'merchants' AND json_extract(q.details, '$.merchantId') = OLD.merchant_id
    AND json_extract(l.value, '$.offerId') = OLD.id
)
BEGIN
  SELECT RAISE(ABORT, 'an offer a quote names is retired, not removed');
END;

-- What a provider's look-up of an account returned for one owner (docs/commerce.md, "Account check"): the
-- holder's name and what is due. A quote for a merchant that checks accounts must carry one of these, made by
-- the same owner for the same merchant and fields, and takes the holder's name from here, never from the model.
CREATE TABLE account_check (
  id TEXT PRIMARY KEY CHECK (length(id) = 23 AND id GLOB 'ck-*'),
  owner TEXT NOT NULL CHECK (length(owner) = 32 AND owner NOT GLOB '*[^0-9a-f]*'),
  merchant_id TEXT NOT NULL REFERENCES merchant (id),
  fields TEXT NOT NULL CHECK (json_valid(fields) AND json_type(fields) = 'object'),
  holder_name TEXT NOT NULL CHECK (length(holder_name) BETWEEN 1 AND 120),
  due_kobo INTEGER CHECK (due_kobo IS NULL OR (typeof(due_kobo) = 'integer' AND due_kobo >= 0)),
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL CHECK (expires_at > created_at)
);

CREATE INDEX account_check_owner ON account_check (owner, merchant_id, created_at);

CREATE TRIGGER account_check_is_kept
BEFORE UPDATE ON account_check
BEGIN
  SELECT RAISE(ABORT, 'an account check cannot be changed');
END;

-- The simulated directory's side of an account check and of an order (checkout/commerce/simulated.py): the
-- accounts its merchants know, and the answer a merchant gives to an order. An order's row is written once, by
-- the first of the test route that presets it and the fulfilment that places it, and only a pending one moves.
CREATE TABLE sim_merchant_account (
  merchant_id TEXT NOT NULL REFERENCES merchant (id),
  reference TEXT NOT NULL CHECK (length(reference) BETWEEN 1 AND 40),
  holder_name TEXT NOT NULL CHECK (length(holder_name) BETWEEN 1 AND 120),
  due_kobo INTEGER CHECK (due_kobo IS NULL OR (typeof(due_kobo) = 'integer' AND due_kobo >= 0)),
  PRIMARY KEY (merchant_id, reference)
);

CREATE TABLE sim_merchant_order (
  quote_id TEXT PRIMARY KEY,
  outcome TEXT NOT NULL CHECK (outcome IN ('delivered', 'pending', 'failed')),
  description TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TRIGGER sim_merchant_order_decided_stays_decided
BEFORE UPDATE OF outcome ON sim_merchant_order
WHEN OLD.outcome <> 'pending'
BEGIN
  SELECT RAISE(ABORT, 'a merchant that delivered or refused an order does not change its answer');
END;
