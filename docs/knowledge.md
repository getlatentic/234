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

The host, not the model, shows where an answer came from, and shows a source only when its text proves the claim
(#645). When a turn read sources, a line follows the answer for each source that holds a figure of the answer
(at most three): `Source: <title> — <link> (read <day>)`. An amount or link in the answer that no source and no
message gave is named too: `Not in the sources I read: …`. Both are notices written from the tool results
(`turns/sources.py`, `runner.py`).

The model does not cite reliably (it gives a passage id, or nothing), so the host checks the answer against the pages:

- **A figure is a claim.** An amount, a percentage or other decimal, a count from a hundred up, and a number under a
  hundred that counts a time (14 days, 8 am, 7 October) or is spelled out (three years). A year, a form number, a
  number of a list and the numbers in a link are not claims: every page has them.
- **The answer's claims are the figures that a page the turn read gave.** A figure the person wrote is theirs, and a
  figure no page gave is the answer's own (a total of two amounts, or one that `Not in the sources I read` names).
- **A source is shown for the claims it holds.** A page that holds a distinctive claim (an amount, a decimal, a count
  of a hundred or more) is shown. A page that holds only a small claim (14 days) is shown when the answer also shares
  three long words with it, so a figure that two pages happen to hold does not make the wrong page a source. A page
  on the same subject that holds none of the answer's figures is not shown, however many words it shares.
- **An answer with no claim from a source** (no figure, or only figures nobody gave) is shown a source only when its
  words clearly carry it: four long words that the person did not write (the words of the question are the subject,
  not the answer), at least half of the answer's long words, and more than any other page. A reply that restates the
  question, or says the sources do not cover it, is shown none unless it states a figure that a page gave. A source
  that is wrong is worse than none.

What this leaves out. A figure spelled in Hausa, Yoruba or Pidgin (`biyar`) is not a claim the host can read, so such
an answer is shown a source by its words only. A source line does not say which claim it backs: an answer with two
amounts from two pages shows both lines, and the person cannot tell which amount is which.

## Evaluation

`evaluation/knowledge_*.py` and `evaluation/retrieval.py`, scored by code with no model judge. The corpus is
invented (`knowledge/eval`): fictional agencies and made-up fees, so a model that gives them has read them. The
`knowledge` split was used while the tool, the prompt and the scorer were built; the `knowledge-held-out` split was
written before the run that quotes numbers (`evaluation/RESULTS.md`).

- `python -m evaluation.knowledge_report FILE` (from `host/`) scores a results file again and tabulates it by kind of
  outcome, with the lines that no page proves;
- retrieval alone: `PYTHONPATH=.:host/src:checkout/src:checkout uv run --project host python -m evaluation.retrieval`
  from the root (recall@5 overall and by language);
- with the real model: `KNOWLEDGE_DIR=../knowledge/eval tools/real-model.sh`, then `python -m evaluation.run
  --split knowledge-held-out --draws 12` from `host/` (see the docstring of `evaluation/run.py`);
- the release gate is `evaluation/gate.py`: recall@5 at least 0.90 (0.85 per language), answers ok at least 85%,
  citations at least 95%, no wrong answer in 150 draws, abstention at least 90%, no injected instruction obeyed in
  36 draws, and no source line that the page does not prove (`evaluation/source_lines.py`: its page holds none of
  the answer's figures, or it stands under an answer that no page carries). It must be met by a run with the real model before an index version is activated or the prompt changes.

Yoruba, Hausa, Pidgin and Igbo questions carry `native_reviewed: false` until a native speaker has read them; no
number is quoted for those languages before then.
