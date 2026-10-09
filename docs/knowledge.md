# Answers from sources

234 answers questions of fact (a fee, the steps to renew a licence) from a curated corpus and shows where each
answer came from. The `knowledge` connector in the connectors Worker serves it from the same D1 database as
the ledger, in its own tables (`checkout/migrations/0008_knowledge.sql`).

## The corpus

`knowledge/sources/<agency>/<id>.md`: front matter, then an excerpt or a paraphrase of one page. Never the page.

```
---
id: frsc-licence-renewal          # lowercase words and hyphens; the file's name
agency: FRSC
title: Renewing a driver's licence
url: https://frsc.gov.ng/...      # https, on the allow-list
content_type: procedure           # guidance | fee | procedure | notice | form
language: en
trust_tier: 1                     # 1 official .gov.ng, 2 agency partner, 3 reputable outlet
status: draft                     # draft | published | retired
retrieved_at: 2026-10-01          # when someone last read the page
reviewed_by: ...                  # a published source has these two
reviewed_at: 2026-10-02
fees:                             # each fee is in the text and checked by a second person
  - {item: Renewal, naira: 15000, verified_by: ...}
---
```

`PYTHONPATH=src uv run python -m tools.knowledge_load check` (in `checkout/`) holds the rules: a published source
has a reviewer; a fee's amount is in the text and is verified by someone other than the reviewer; the link is an
https link on the allow-list (`.gov.ng` and a short named list; a look-alike such as `gov.ng.evil.com` is
refused); tier 1 is an official `.gov.ng` page; the text is at most 6,000 characters; ids are unique.
`report` lists unreviewed, retired and stale (retrieved more than 180 days ago) sources, for the weekly look.

## Loading

`sql` prints statements that replace what the database holds (sources no longer in the corpus are deleted):

```
PYTHONPATH=src uv run python -m tools.knowledge_load sql > corpus.sql
wrangler d1 execute <ledger database> --remote --file corpus.sql
```

Each source is cut into passages of up to 700 characters (`knowledge/chunker.py`: a passage is a slice of the
text at known offsets, ordered, with only whitespace left between them). The index is full text (FTS5, BM25) over
the *folded* passage: lowercase, accents and tone marks dropped, Hausa's hooked letters plain (`knowledge/normalise.py`).
A question is folded the same way, so "iforukosile" finds "iforúkọsílẹ̀".

## What the model gets

Three read-only tools: `search_knowledge` (filters `agency`, `content_type`, `trust_tier`), `open_source` (a
passage and its neighbours) and `list_sources`. A source is served only while `status = 'published'`: that is a
condition of every query, not an argument, and the tools reject any argument they do not declare.

A passage reaches the model cleaned and quoted as data (`knowledge/sanitise.py`, `render.py`): markup and invisible
characters removed, a link whose host is not on the allow-list replaced by `[link removed]`, and every line shown
behind `>` under a header line of the server's own with the source, link, retrieved date and tier. The result
says `untrusted: true`.
