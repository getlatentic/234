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
keywords: [tax, registration fee]  # optional: words to find the page by (English for a Hausa page); never shown
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
passage and its neighbours) and `list_sources`. A filter is the model's guess (it names an agency from memory), so
it puts its matches first and does not keep the others out: a wrong guess does not hide the right page. A source is served only while `status = 'published'`: that is a
condition of every query, not an argument, and the tools reject any argument they do not declare.

A passage reaches the model cleaned and quoted as data (`knowledge/sanitise.py`, `render.py`): markup and invisible
characters removed, a link whose host is not on the allow-list replaced by `[link removed]`, and every line shown
behind `>` under a header line of the server's own with the source, link, retrieved date and tier. The result
says `untrusted: true`.

## What the person sees

The host, not the model, shows where an answer came from. When a turn read sources, a line follows the answer for
each source it draws on (at most three; it shares a number or three long words with a passage the turn read):
`Source: <title> — <link> (read <day>)`. An amount or link in the answer that no source and no message gave is
named too: `Not in the sources I read: …`. Both are notices written from the tool results (`turns/sources.py`,
`runner.py`).

## Evaluation

`evaluation/knowledge_*.py` and `evaluation/retrieval.py`, scored by code with no model judge. The corpus is
invented (`knowledge/eval`): fictional agencies and made-up fees, so a model that gives them has read them. The
`knowledge` split was used while the tool, the prompt and the scorer were built; the `knowledge-held-out` split was
written before the run that quotes numbers (`evaluation/RESULTS.md`).

- retrieval alone: `PYTHONPATH=.:host/src:checkout/src:checkout uv run --project host python -m evaluation.retrieval`
  from the root (recall@5 overall and by language);
- with the real model: `KNOWLEDGE_DIR=../knowledge/eval tools/real-model.sh`, then `python -m evaluation.run
  --split knowledge-held-out --draws 12` from `host/` (see the docstring of `evaluation/run.py`);
- the release gate is `evaluation/gate.py`: recall@5 at least 0.90 (0.85 per language), answers ok at least 85%,
  citations at least 95%, no wrong answer in 150 draws, abstention at least 90%, no injected instruction obeyed in
  36 draws. It must be met by a run with the real model before an index version is activated or the prompt changes.

Yoruba, Hausa, Pidgin and Igbo questions carry `native_reviewed: false` until a native speaker has read them; no
number is quoted for those languages before then.
