-- The guidance 234 answers from: one row per curated source and its passages, with a full-text index over the
-- folded passage text (docs/knowledge.md). The corpus lives in git (knowledge/sources); tools/knowledge_load.py
-- turns it into these rows. Public data: no row belongs to an owner.
--
-- A source is served only while it is 'published', and it can only be published with a reviewer.

CREATE TABLE knowledge_source (
  id TEXT PRIMARY KEY,
  agency TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  content_type TEXT NOT NULL CHECK (content_type IN ('guidance', 'fee', 'procedure', 'notice', 'form')),
  language TEXT NOT NULL,
  trust_tier INTEGER NOT NULL CHECK (trust_tier BETWEEN 1 AND 3),
  status TEXT NOT NULL CHECK (status IN ('draft', 'published', 'retired')),
  retrieved_at TEXT NOT NULL,
  published_at TEXT,
  reviewed_by TEXT,
  reviewed_at TEXT,
  checksum TEXT NOT NULL,
  CHECK (status <> 'published' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);

CREATE INDEX knowledge_source_agency ON knowledge_source (agency, status);

CREATE TABLE knowledge_passage (
  seq INTEGER PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,
  source_id TEXT NOT NULL REFERENCES knowledge_source (id) ON DELETE CASCADE,
  ord INTEGER NOT NULL,
  start_offset INTEGER NOT NULL,
  end_offset INTEGER NOT NULL,
  text TEXT NOT NULL,
  folded TEXT NOT NULL,
  UNIQUE (source_id, ord),
  CHECK (start_offset >= 0 AND end_offset > start_offset)
);

CREATE VIRTUAL TABLE knowledge_fts USING fts5(folded, tokenize = 'unicode61 remove_diacritics 2');

CREATE TRIGGER knowledge_passage_indexed AFTER INSERT ON knowledge_passage
BEGIN
  INSERT INTO knowledge_fts (rowid, folded) VALUES (new.seq, new.folded);
END;

CREATE TRIGGER knowledge_passage_unindexed AFTER DELETE ON knowledge_passage
BEGIN
  DELETE FROM knowledge_fts WHERE rowid = old.seq;
END;
