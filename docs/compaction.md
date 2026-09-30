# Context compaction: a long chat keeps working

Measured 2026-09-30 on local workerd, local D1, the scripted model and, where it says so, `openai.gpt-oss-120b` on a Bedrock endpoint. Nothing was deployed. Prior art read first: pi's `compaction.md` (cut points, keeping recent tokens, iterative summaries, a tool call never split from its result); the ideas are used, the coding-agent parts (files, branches, split turns) are not.

## Decision

- **The log is never rewritten.** A chat's event log stays complete; the page, A2A and crash recovery read all of it. Compaction is one more event, `compaction`, appended by the chat's runner, and it changes only what the model is sent.
- **What the model reads:** the system prompt, then the latest compaction's summary as one clearly labelled message, then every message the log holds from that compaction's cut on, folded as before (`messages.render`). A compaction never makes the model read less than a summary plus the recent conversation.
- **When:** before a model call, when the request is over `COMPACT_AT` of `CONTEXT_WINDOW_TOKENS`. The person's reply waits for one more model call (the summary), once every few tens of turns, and never for more than the timeout.
- **Who writes the summary:** the product's own model (`openai.gpt-oss-120b`) through the same client, never a Claude model. Its facts are checked by rules, and completed by rules when the model misses them.
- **If no summary can be had** (error, timeout, junk, budget) the turn does not fail: the context is trimmed by rule and the compaction is recorded as a `fallback` with the reason.

## The event

`compaction` is a chat-level event (no task, so A2A never sees it). Its `ref` is its identity, `compaction:<first>-<last>:<pruned_before>`: a compaction is what range it covers.

| Field | Meaning |
|---|---|
| `covers.first`, `covers.last` | the first and last seq the compaction newly summarises; the events after `last` are kept word for word |
| `summary` | the text the model reads (for a fallback, the previous summary carried, with a facts block for what was dropped) |
| `tokens.before`, `tokens.after` | the estimate of the request before and after, corrected as below |
| `model` | the model that wrote it (empty for a fallback) |
| `trigger` | `auto`, `manual` or `fallback` |
| `reason` | for a fallback, why no summary was made (for operators; the person is not shown it) |
| `verified` | `model` (complete on the first try), `retried` (complete after asking again), `block` (completed by a facts block written by rule), `trimmed` (a fallback) |
| `pruned_before` | bulky tool results older than this seq are shown as stubs in what the model reads |
| `calls`, `ms` | model calls made for it, and how long the whole compaction took |

## Size of the context

`turns/tokens.py`: a request is `chars / 4` per message plus the tool definitions it carries. The endpoint's own count corrects it. Asked with `stream_options: {include_usage: true}`, the Bedrock endpoint ends the stream with a chunk with no `choices` and `usage: {prompt_tokens, completion_tokens, total_tokens}` (checked 2026-09-30); the reply event records `estimate` (ours, before the call) and `usage`. The ratio of the latest pair (clamped 0.5 to 3) multiplies the next estimate, so text that costs more or less than four characters a token (Pidgin, Yoruba, the naira sign, JSON) is corrected without a rule about characters. On the real endpoint the first request of a chat was estimated at 3,122 tokens and counted at 2,198 (ratio 0.70): `chars / 4` overcounts this mix, mostly the tool definitions (about 10,000 characters).

## The cut

`compaction/plan.py`, over units: a message, or a reply together with the results of its tool calls. A cut is allowed only where every message before it has lower seqs than every message after it, in the order the model reads them (a reply sits after the last event it had read, `upto`, not where it was appended). That one rule keeps:

- a tool call with its result (a call that has no result yet pins its reply and everything after it);
- a reply with the question it answers when a message arrived while the model streamed;
- "after the cut" a single seq.

Also, in order: at least `KEEP_RECENT_TOKENS` are kept; the flow of the **latest open quote** (phase `awaiting_approval`, `awaiting_checkout`, `awaiting_otp` or `processing`, and, before approval, not past its expiry) is kept from the reply that made it, so the person can approve it with its whole request in front of the model; the cut falls where a person's message starts when it can, else between replies of one turn; and it must cover at least `max(300, KEEP_RECENT_TOKENS / 2)` tokens, so a context that a compaction would barely shrink is not compacted again and again. An older open quote is summarised: its id, amount and state are in the summary and the facts block, and its card is unaffected (cards read the log, not the model's context).

## What the summariser is shown, and what it writes

`compaction/transcript.py`: one labelled line per event in the covered range (`[Person]`, `[Assistant]`, `[Assistant called]` with shortened arguments, `[Quote made]` and `[Quote update]` from the quote's own fields), scrubbed (`scrub.py`: links, `sk_`/`pk_` keys, labelled secrets, bearer tokens, one-time codes, any 32-character run, card numbers). The approval token, the checkout link and every other field of a card are not in it. **No tool result text is in it**, only whether the call worked: merchant names, menus and whatever else a connector returns are where an instruction can be planted, and what matters of a result is on the card (found in review, see "Where this differs").

The model is asked for six sections: *Asked and decided*, *Facts the person stated*, *Done* (quotes and their states), *Pending*, *Open questions*, *Tone and language* (English, Pidgin or Yoruba), told to copy amounts, phone numbers, account numbers and quote ids digit for digit, never to write links, codes, tokens, keys or card numbers, and to treat the conversation as data. A later compaction sends the previous summary with the newly covered events ("update it"). A summary that is not in the sections, is under 80 characters, ends for any reason but `stop`, or is over 3,000 tokens is junk.

**Verification** (`compaction/facts.py`). The facts are read out of the log by rule, from everything before the cut (not from the previous summary, so an error cannot accumulate): every amount (as `₦5,000`, `N5000`, `5k`, `2500 naira`, `50000 kobo`; in kobo), phone number (any spelling: `07031234567`, `0703 123 4567`, `+234 703 123 4567`), account number (ten digits, however grouped) that the person typed or a connector quoted, and every open quote id. Each must be in the summary (a bare number in a summary counts as naira), or in the events kept after it. If something is missing the model is asked once more with the missing facts listed; if it still misses, the facts are appended as a block written by rule: every amount, number, and each quote with its state now (open first, the latest 25; the rest counted by state). What the assistant or a tool said is never a required fact.

## When there is no summary

`Compactor._trimmed`. A summary call that raises, times out (`COMPACTION_TIMEOUT_SECONDS`, per call), is junk, or cannot be paid for (a summary is a model call against the same daily caps as a reply) is followed by: stub the bulky tool results older than the recent window (`[result omitted: 30 items]`, read from the log, never stored over it), and if the request still does not fit 75% of the threshold, drop the oldest whole units, as few as will fit, keeping the latest open quote while it can be kept. The previous summary is carried and a facts block for the dropped events is added. The event is a `compaction` with `trigger: fallback` and the `reason`; the operator's notice is a `WARNING` log line (`Compaction of chat <id> fell back to trimming: <reason>`), and the person sees nothing but the one quiet line. Whatever the compactor raises, the round goes on without it (`TurnRunner._compacted`).

The same trim runs when the endpoint refuses a request as too long (`ContextTooLong`): the round is asked again once after the context is cut to half of what it was.

## One writer, once, and after a crash

- Every compaction of a chat goes through one `Compactor` (one lock) of its one Durable Object; a turn's and a person's compaction cannot interleave.
- The append is one statement (`EventLog.append_next_of_type`): it inserts only while the newest compaction is the one the decision was made against and no event of that type has this `ref`. Two writers that mean the same thing make one event; the loser gets nothing and the runner carries on with the log as it is. A manual request that arrives while another is being served answers with the event the first wrote.
- A kill in the middle of a summary leaves no event, so nothing is half written; the watchdog alarm resumes the turn, which compacts again from the log. `tests/crash_probe_compaction.py` kills the Worker while the summary streams: the log the kill left has no compaction and no gap, the turn was resumed, one compaction was written and the turn answered.
- A chat being deleted closes its compactor before its log is erased, so a compaction in flight does not write into a deleted chat.

## The person's side

The page shows the history unchanged and, where the compaction sits, one quiet line, "Earlier messages were summarised", that opens onto the summary ([chat-ui.md](chat-ui.md#after-a-compaction)). `POST /c/<id>/compact` (owner only; 403 for a share-link guest, 404 for a stranger; twelve a minute; a summary costs a model call) compacts now whatever the size, for trying it; the body may carry `keep_recent_tokens`. It answers `{"compacted": true, "seq", "trigger", "verified", "tokens", "ms"}` or `{"compacted": false}` when there was nothing worth covering.

A2A is unaffected: a compaction has no task, and a task's events, stream and history are its own. The sandbox and the cards are unaffected: a card's calls go to the connector through the log's card events, not through the model's context. The approval token and card data still never reach the model; they are also kept out of the summariser and out of every summary (`test_transcript.py`, `test_worker_compaction.py`, and the guardrails of the mutation check).

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `CONTEXT_WINDOW_TOKENS` | 32000 | the window compaction plans for. gpt-oss-120b on this endpoint accepts 262,144 (its own error says so); the default is low on purpose, to keep the cost of each turn down, and a person who wants a longer memory raises it |
| `COMPACT_AT` | 0.6 | the share of the window that starts a compaction (19,200 tokens at the default) |
| `KEEP_RECENT_TOKENS` | 6000 | the end of the conversation that stays word for word |
| `COMPACTION_TIMEOUT_SECONDS` | 45 | how long one summary call may take; there are at most two per compaction |
| `LLM_STREAM_USAGE` | on (`0` turns it off) | ask the endpoint for the token count of each request |
| `LLM_ROUND_DEADLINE_SECONDS` | 120 | how long one model round may stream before the turn ends as failed (not compaction's own, but found by its probes) |

`tools/up.sh` passes the first four to the local stack. The tool definitions and the system prompt are about 3,000 estimated tokens (1,900 to 2,200 counted), so a window under about 10,000 leaves room for little else.

## Measured

**Scripted** (the scripted model and summariser; local workerd; `tests/test_worker_compaction.py` on a stack with a window of 8,000 tokens, compacting at 0.75, keeping 500): a chat of 37 messages in English and Pidgin, every sixth buying airtime (paid through the simulated bank, declined, or left open) was compacted three or more times; the tokens of every request stayed at or under the threshold by the endpoint's own count (the scripted endpoint counts a token per three characters) within 15%; every compaction's summary held every amount, number and open quote of what it covered; the quote still waiting for the person was in front of the model and could be approved after the compactions; "what was the last amount I paid?" was answered from the summary. The in-process version is 150 turns (`test_compaction_long.py`): 15 quotes in five states, two or more compactions, the same checks. A compaction took a median of 80 ms (maximum 131 ms, 16 of them) with the scripted summariser: the code's own cost, and the floor under the real numbers below.

**Real model** (`openai.gpt-oss-120b`, a Bedrock endpoint, 2026-09-30; `host/tests/compaction_probe.py` through `tools/real-model.sh compaction 5`; window 12,000 tokens, compacting at 0.6 (7,200), keeping 2,500). Each chat is 150 turns in English and Pidgin: small talk, a name to be called, an account number, two amounts (a rent, a wage), fifteen airtime quotes (paid, declined, the last left open); then five questions about its past, scored without a model. Two runs of five chats; eight of the ten chats finished (see "What failed"):

| | Run 1 (4 chats) | Run 2 (4 chats) |
|---|---|---|
| Compactions (all `auto`, none a fallback) | 24 | 26 |
| Complete on the first try / after asking again / completed by rule | 20 / 3 / 1 | 21 / 4 / 1 |
| A compaction took (median per chat, maximum) | 4.3 to 6.3 s, 14.5 s | 3.1 to 4.6 s, 13.5 s |
| A plain turn (median) and a turn that compacted (median) | 0.9 s, 5.9 to 7.4 s | 0.8 to 1.0 s, 4.4 to 5.8 s |
| Added to a turn that compacted | 5.0 to 6.5 s | 3.5 to 5.0 s |
| Context before and after a compaction (median per chat, tokens) | 7,240 to 7,285, then 5,780 to 5,940 | 7,235 to 7,318, then 5,808 to 5,958 |
| Largest request (provider's count) | 7,201 to 7,450 | 7,192 to 7,341 |
| Summary size | 335 to 447 tokens | 363 to 481 tokens |
| Facts (amounts, phones, accounts) in the final context | 79 of 79 | 79 of 79 |
| Facts in the model's own words, per summary | 245 of 246 | 269 of 270 |
| Questions answered right | 16 of 20 | 17 of 20 |

So a compaction happened about every 20 to 25 turns, cost the person that turn about five seconds more (a plain turn is about one second), and kept the real request at the threshold and no more (the largest, 7,450 tokens, is 3.5% over 7,200). Of 50 compactions the model's first summary held every fact in 41, the second try (with the missing facts listed) in 7, and in 2 the facts block written by rule completed it: a summary the model wrote alone would have lost a fact in 9 of 50; none reached the model's memory as a loss, because the final context held every amount and number in all eight chats.

The 7 wrong answers of 40: three were "what is my shop rent?" answered "I can't see that" although the amount was in the summary (the system prompt tells the model to decline what is not a money task, and it reads a question about the past as one; not a memory failure), one was "Ada's account" answered with a run of no-break spaces and dots (the real model sometimes degenerates like that: 3 of the 20 answers of run 2 held such runs, two of them before a right answer), one was the wrong "last amount I paid" (the model named the payment before the latest; it had both in front of it), and two were the same chat (seed 4) in both runs, **"what name did I ask you to call you?"**: the summariser left "Oga Bukky" out of every summary of that chat. A name or a preference is not a fact the rules check (only amounts, numbers and open quotes are), so nothing retried it. This is the gap of the design; see the limits.

The count the endpoint returned for the first request of a chat was 2,198 against our estimate of 3,122; the ratio correction took it from there, and the real requests in the table are the provider's own counts.

No control was run (the same chats with the window at 262,144, so no compaction) to say how many of the 7 wrong answers a chat that was never compacted would also give.

**What failed.** In both runs chat 5 (seed 5) never finished: a turn began (`turn.started`, the context at about 7,000 tokens) and the model's stream neither ended nor failed, for at least five minutes, until the stack was stopped. Phase markers showed the round had passed the tool list and the compaction check and was inside the model call, so it is not the compaction. A stall with no bytes is ended by the client's timeout (tested: 60 s), so the stream was sending something without finishing (probably a reasoning stream that did not stop: there is no output ceiling, and the model does degenerate now and then). The runner had no deadline on a whole model round. It now has one (`LLM_ROUND_DEADLINE_SECONDS`, 120 s): the turn ends `failed` with "The model took too long to answer." (`test_runner.py`, a mutation-check entry). Two stalled rounds in about 1,640 real model calls.

## Where this differs from the brief, pi and the review

- **No tool result text goes to the summariser** (the brief had pruned results sent): a review of the first version showed a short result can carry a planted instruction into every later round through the summary. The quote facts come from the card.
- **A compaction may happen between the rounds of an open turn**, not only between turns: the cut is torn-free and the latest open quote is pinned, which lets one tool-heavy turn be handled. The seq rule replaces "the cut is at an input event".
- **The facts are read from the whole log before the cut**, not from the previous summary plus what is new: the log is complete, so a fact dropped once is still required next time and nothing drifts.
- **The fallback also writes a facts block** for what it drops (the brief said prune, then truncate): a trimmed chat still knows its amounts and its open quotes.
- **A refusal for length is handled**: the research review asked for it (finding 2). The real endpoint sends it as an error event in a stream that began with HTTP 200 (measured: a 250,000-token prompt got `data: {"error": ...}` after `200 OK`). The model client used to read such an event as an empty reply; it now raises, and raises `ContextTooLong` when the words say the prompt did not fit.
- **Event identity** includes `pruned_before`, since a fallback that only stubs covers nothing new.
- Pi's split turns, branch summaries and file tracking are not ported.

## Limits, and what is not verified

- `EventLog.context()` still reads every non-text event of the chat on every round (review finding 3): compaction bounds what the model is sent, not what D1 is asked for. A chat of thousands of turns makes each round read thousands of rows. Bounding the read is safe only with a separate read of the call ids (`calls.used_ids`), and was not done.
- Only the latest open quote is pinned; an older one is summarised (finding 4). Its state is in the summary and the block.
- **Names and preferences are not checked.** Only amounts, phone numbers, account numbers and open quotes are read out of the log by rule. A name the person asked to be called, or a standing preference, is left to the summariser, and in 2 of 8 real chats (the same script twice) it was lost and no retry followed. A cue-based extractor ("call me X", "my name is X") checked like an amount is the obvious next step, and was not built.
- Words are not amounts: "five thousand naira" is not found by the extractor, so a summary that drops it is not noticed. Digits, `k`, `₦`, `N`, `naira`, `kobo` are.
- The states `paid` and `declined` in the model's own sections are not verified; the block gives them by rule only when a fact is missing. The quote states a summary gives come from the `[Quote update]` lines, which come from the log.
- The summariser has no output cap (a cap made reasoning consume the budget: see model-behaviour.md); a summary over 3,000 tokens or a call over the timeout is a failure.
- The estimator counts characters. A conversation of another kind (long Yoruba, emoji) is corrected by the provider's count after the first reply, not before it.
- Only the local stack was used. Nothing ran on Cloudflare, so production eviction during a summary (a summary can take ten seconds or more), D1 latency and billing are not observed. The crash test is a SIGKILL of the whole local Worker.
- The real-model runs are one model, one endpoint, one afternoon, English and Pidgin, airtime only; transfers, menus and other connectors were not in the long chats.
