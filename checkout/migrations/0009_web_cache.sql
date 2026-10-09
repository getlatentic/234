-- What the web tool fetched, kept for an hour so the same page or robots.txt is not fetched again
-- (docs/web.md). Public pages only: no row belongs to an owner.

CREATE TABLE web_cache (
  url TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('page', 'robots')),
  status INTEGER NOT NULL,
  final_url TEXT NOT NULL,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  truncated INTEGER NOT NULL CHECK (truncated IN (0, 1)),
  fetched_at INTEGER NOT NULL,
  PRIMARY KEY (url, kind)
);

CREATE INDEX web_cache_fetched ON web_cache (fetched_at);
