-- How many web searches each person has made today (docs/web.md): a search costs money, so a person has a
-- few a day. One row per owner and UTC day.

CREATE TABLE web_search_use (
  owner TEXT NOT NULL,
  day TEXT NOT NULL,
  used INTEGER NOT NULL CHECK (used >= 0),
  PRIMARY KEY (owner, day)
);
