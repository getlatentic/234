-- What 234 remembers for a signed-in account. Every row belongs to one owner (the key the chat host names in
-- the memory owner header) and every statement that reads or writes one names that owner.
--
-- An entry is written only from a proposal the person confirmed on a card (memory_proposal). A forgotten entry
-- keeps its row with deleted_at set until the retention period has passed, so "Undo" can bring it back; the
-- purge then deletes it for good.

CREATE TABLE memory_entry (
  seq INTEGER PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,
  owner TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('recipient', 'preference', 'fact')),
  title TEXT NOT NULL,
  hook TEXT NOT NULL,
  body TEXT NOT NULL,
  -- 'stated': the person said it and confirmed it on a card; 'card': a bank lookup the person confirmed on a card.
  source TEXT NOT NULL CHECK (source IN ('stated', 'card')),
  bank_code TEXT,
  account_number TEXT,
  account_name TEXT,
  verified_at INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  last_used INTEGER NOT NULL,
  deleted_at INTEGER,
  CHECK (
    (kind = 'recipient') = (
      bank_code IS NOT NULL AND account_number IS NOT NULL AND account_name IS NOT NULL AND verified_at IS NOT NULL
    )
  )
);

-- The memory index of one owner is one range scan of this index: live rows (deleted_at IS NULL), newest use first.
CREATE INDEX memory_entry_live ON memory_entry (owner, deleted_at, last_used);

-- The purge finds forgotten rows without reading the live ones.
CREATE INDEX memory_entry_forgotten ON memory_entry (deleted_at) WHERE deleted_at IS NOT NULL;

-- Full-text search over what the person can read in their notes. The index keeps the text of live rows only.
CREATE VIRTUAL TABLE memory_fts USING fts5(
  title, hook, body,
  content = 'memory_entry', content_rowid = 'seq',
  tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER memory_entry_indexed AFTER INSERT ON memory_entry WHEN new.deleted_at IS NULL BEGIN
  INSERT INTO memory_fts (rowid, title, hook, body) VALUES (new.seq, new.title, new.hook, new.body);
END;

CREATE TRIGGER memory_entry_reindexed AFTER UPDATE OF title, hook, body, deleted_at ON memory_entry BEGIN
  INSERT INTO memory_fts (memory_fts, rowid, title, hook, body)
    SELECT 'delete', old.seq, old.title, old.hook, old.body WHERE old.deleted_at IS NULL;
  INSERT INTO memory_fts (rowid, title, hook, body)
    SELECT new.seq, new.title, new.hook, new.body WHERE new.deleted_at IS NULL;
END;

CREATE TRIGGER memory_entry_unindexed AFTER DELETE ON memory_entry WHEN old.deleted_at IS NULL BEGIN
  INSERT INTO memory_fts (memory_fts, rowid, title, hook, body)
    VALUES ('delete', old.seq, old.title, old.hook, old.body);
END;

-- What a card asks the person to decide. `payload` is the validated content of the entry to write; a recipient's
-- payload holds the bank's own answer (the resolved account name), never the model's. `state` moves once:
-- pending to applied or discarded, and an applied forget to undone.
CREATE TABLE memory_proposal (
  id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  op TEXT NOT NULL CHECK (op IN ('remember', 'update', 'forget')),
  target_id TEXT,
  payload TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('pending', 'applied', 'discarded', 'undone')),
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  decided_at INTEGER
);

CREATE INDEX memory_proposal_owner ON memory_proposal (owner, state, created_at);
CREATE INDEX memory_proposal_expiry ON memory_proposal (expires_at);
