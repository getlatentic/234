# Durable chats: the design, and the evidence for it

All numbers are from local workerd (`pywrangler dev`), local D1 and the scripted model, on one laptop, 2026-09-29. Nothing was deployed. Where production behaviour differs or is unknown, it says so.

## Decision

- **Turn runner: one Durable Object per chat.** It is the only writer of that chat's log, runs the turn loop in the background so a turn outlives every client, and pushes each new event to attached sockets. An alarm is its watchdog: it restarts a turn that a restart cut off.
- **Live transport: hibernating WebSocket to the chat's Durable Object.** Server-sent events with `Last-Event-ID` stay as the fallback and as what A2A streams over. Both read the same log from a cursor.
- **The log is the conversation.** An append-only event table in D1, `(chat, seq)` unique and gapless. The page, the model's context, the A2A view and crash recovery are all folds of it. The Durable Object holds no state that the log does not.
- **Queue consumer and `ctx.waitUntil` stay in the tree as the measured alternatives** (`host/src/turns/alternatives/`, `TURN_RUNNER=queue|waituntil`). They run the same `TurnRunner`. They lost on evidence below.

## What was built

```
browser tab ─ WebSocket ────────────┐
browser tab ─ SSE (fallback) ─┐     ▼
A2A caller ── SSE ────────────┤   Worker ── upgrade + signed ticket ──▶ Chat Durable Object (one per chat)
                              │     │                                     │ ChatCore: submit, run turns, push,
                  Django (WSGI)◀────┘                                     │ relay card calls, watchdog alarm
                  pages, history, auth, A2A views                          │
                              │                                            ▼
                              └──────────── reads ────────────────────▶ D1: chat_event (the log)
```

- `host/src/turns/` has no Django import. It holds the log (`eventlog.py`), the fold (`fold.py`: `next_action`, task state; `messages.py`: the model's messages), the runner (`runner.py`), the model client, the async MCP hub, the idempotency key of a quote call (`idempotency.py`) and the rules for a reply's tool calls (`calls.py`), budgets, input checks, the fan-out (`fanout.py`), the object (`chat_core.py`, `chat_object.py`) and the compaction of a long context (`compaction/`).
- **The loop is derived from the log, not held in memory.** Each step reads the log, asks `next_action` what is left (unanswered tool calls, then anything the model has not been shown), does one thing and appends the outcome. A reply records how far it read (`upto`), so a message that arrives while the model streams is answered by the next round and sits after the reply that did not know of it in the model's context.
- **Event kinds:** `user`, `card_message`, `card_context`, `turn.started`, `text` (streamed, coalesced to about one event per 150 ms), `assistant` (with `finish_reason`), `tool`, `card` (with the approval token, browser-owner only), `card_state` (no `_meta`), `notice`, `round.aborted`, `turn.resumed`, `turn.finished`, `compaction` (the log is never shortened: a compaction is one more event that says what the model reads from now on; see [compaction.md](compaction.md)).
- **A socket is sent event N+1 only after N.** Its cursor is its hibernation attachment, so an evicted and woken object still knows where each socket is. A gap makes the socket catch up from the log; a reconnecting client sends `{"attach": cursor}` and gets what it missed, then the live events. `{"reset": true}` tells a client whose cursor is past the end to reload.
- **The WebSocket upgrade is answered by the Worker before Django**, from a one-minute HMAC ticket that Django minted after checking ownership, plus an `Origin` check. Django's sync ORM is never on the Durable Object's path; the object talks to D1 with raw SQL. `chat_event` is created by a Django migration and written by one atomic `INSERT ... SELECT MAX(seq)+1 ... RETURNING seq`.
- **Card state is server state.** A card's tool call goes through the object, which records a changed quote as `card_state` and pushes it: an approval in one tab reaches the card in another, and a signed payment webhook (`POST /hooks/payment`, sent by the connector when the simulated checkout records a payment) reaches open cards, including ones whose object was hibernated.
- **A chat is made by its first message.** The home page mints an id and stores nothing; `POST /c/<id>/start` makes the chat row and hands the message to the object, and a second start for the same id joins it. D1 reports the loser of two simultaneous inserts as its own exception (not Django's `IntegrityError`), which once made one in twenty double starts answer 500; `claim_chat` looks the row up again. See [chat-ui.md](chat-ui.md).
- **Visitors and accounts.** A visitor is a signed HttpOnly cookie (Django signing, salted) and chats belong to that id; a person who signs in with Google ([auth.md](auth.md)) is an owner of their own (`u:` and an HMAC of their Firebase uid), the same on every device. Chats belong to that owner. A share link (one hour) lets another device in. Rate limit is per visitor; the model cap is per visitor and global, each one conditional `UPDATE`. The spending allowance is per visitor too: the chat's Durable Object names the chat owner's key to the connectors on every tool call, its own and a card's (see REPORT.md, "Each visitor's own daily allowance").
- **A2A** (`host/src/a2a/`) is Django views on the same log: the HTTP+JSON binding, bearer token per agent, `A2A-Version` required (a caller that names none is taken for 0.3 and refused), CORS allowlist (`*` refused at startup). A message is an input to the caller's own chat; a task is what the loop did with it; a stream is the log read for that task, so subscribing again after a dropped stream works. `INPUT_REQUIRED` carries a handoff link for the person and no card or token.

## Signing in moves chats while their objects are alive

At sign-in the anonymous visitor's chats become the account's: one `UPDATE` of `chat_chat.owner`, no row of any log touched ([auth.md](auth.md#the-design)). Two consequences for the object:

- **It reads its owner every time it needs it** (`ChatCore._owner_of_chat`; it used to keep the first value it read). A live object, or one woken later, makes its next tool call and its next card call for the new owner's key. The cost is one indexed D1 read per turn and per card call. A turn already running keeps the owner it started with for its remaining calls; the idempotency key of a call is derived from the owner as it was (`derive_key` takes the ledger owner), so a call retried after the move makes a new quote instead of returning the old one, which is the right thing for a quote the account cannot reach anyway. Tested in `tests/test_chat_core.py`.
- **A quote made under the anonymous key stays bound to it** (the connectors scope every quote, approval and limit by owner). An approval card still open in an adopted chat therefore calls the connector under the account's key, which answers `QUOTE_NOT_FOUND`; the card turns that answer into its own **"No longer available"** state (neutral, no buttons, no error text), not an error line and not an approvable card. Nothing was approved or paid by that. The card learns it when the person presses Approve or Decline, or when the quote's expiry makes it ask; it is not refreshed at adoption. A menu card is not bound to a quote until it orders, so an open menu should keep working and order under the account (not exercised). `conformance/chat-auth.mjs` does this end to end (an anonymous airtime card, a sign-in, the chat reopened, Approve pressed) and `conformance/card-states.mjs checks` covers the card's state for a transfer and an airtime card; screenshots `docs/screens/auth-adopted-card-no-longer-available.png`, `card-transfer-gone-*.png`.

## Retries and the idempotency key

A quote-making tool takes an `idempotency_key`, and the connectors' ledger answers the same owner, key and request with the quote it already made. The model is not offered the field and never chooses a key (its measured choices repeated across chats; see [model-behaviour.md](model-behaviour.md#idempotency-keys)). The runner gives the hub a key for each model-originated call, and the hub puts it in the arguments of a tool whose schema has the field, over anything the model sent.

- **The key** is the first 40 hex characters of a SHA-256 over (ledger owner, chat id, the call's id): opaque, stable, and inside what the connectors accept (8 to 64 of letters, digits and `._:-`). A different owner, chat or call gives a different key.
- **The call id is in the log before any tool runs.** The `assistant` event carries `tool_calls[].id`; the tool's result is matched to it by `call_id`. A turn resumed after a restart reads the same ids and so derives the same key: a call that had reached the connector but had no result logged is made again with its own key and the ledger returns its quote. Nothing is derived from a clock or a counter.
- **Ids are made unique before they are logged.** The log and the model's context pair results with calls by id, so an id may not repeat in a chat. A provider that leaves the id empty, or numbers calls from zero in every reply, would otherwise make a new request look like an answered one (and, for a key, a replay). Such an id is prefixed with the id of its reply (`with_distinct_ids`); ids a provider made well are kept.
- **A request repeated in one reply is made once.** For a tool that takes a key, a call with the same tool and arguments as an earlier call of the same reply is not sent: its result is the first's, behind a line saying it was not made again, and it records no card. The decision and its reasons are in model-behaviour.md. The comparison is over the log's own record of the reply, so after a restart in the middle of a reply the repeat is still a repeat and only the calls without a result run.

Where a crash can fall, and what shows each case:

| Crash | What happens | Shown by |
|---|---|---|
| Before the `assistant` event is logged (the model is still streaming) | No tool has run. The half reply is discarded and the model is asked again, with new call ids | `crash_probe` (slow reply) |
| After the connector answered, before the `tool` event is logged | The call is run again with the same id, so the same key, and the ledger returns the quote it made: one quote | `tests/test_runner_keys.py` (a ledger double that dies after answering), and the real ledger's behaviour for a repeated key, a new key and a changed request in `tests/test_worker_keys.py` |
| After the `tool` event is logged | The call has its result and is not run again | `tests/test_runner_keys.py`, and `crash_probe do quote`: the Worker was killed while the answer that follows the quote streamed; the turn resumed (`turn.resumed` 1, `round.aborted` 1), finished 36 s after the kill and the log holds one `tool` and one `card` |

The middle row was not produced on a real Worker: the window between the connector's answer and the log write is a few milliseconds, and a kill that lands in it cannot be aimed. It is shown by a runner killed at exactly that point, against a ledger that behaves as the real one does, and by the real ledger's answers to the same key.

## The deciding test, and what it decided

`host/tests/test_worker_durable.py` runs once per runner against local workerd. Each of the six tests passes for all three runners (18 of 18):

1. Start a turn on a slow model, kill the client mid-stream, wait until the turn is over, reconnect with `Last-Event-ID`: the replay joins the first part with no gap or duplicate, equals a fresh full read of the log, the reply is whole, the turn finished while no client was attached.
2. A pending approval survives, is replayed to a second tab, and approving from that tab is recorded as `card_state`.
3. The model is never sent the approval token (`tool_choice: auto` and `reasoning_effort: low` are on the wire).
4. Two tabs of one visitor read identical events in identical order.
5. Two chats run at once, neither mixes with the other, and the run takes the longer turn's time, not the sum.
6. A message sent during a turn is answered in the same task.

So local correctness does not separate the runners. What does:

| | Durable Object | Queue consumer | `ctx.waitUntil` |
|---|---|---|---|
| SIGKILL the Worker mid-turn, start it again (`tests/crash_probe.py`) | **Recovered by itself**: the alarm fired, the half reply was discarded (`round.aborted`), the turn resumed and finished with the whole text, 42 s after the kill (15 s of it restarting; watchdog 30 s), no client attached | Not recovered in 134 s: the in-flight message did not come back on local workerd | Not recovered in 133 s |
| Push to a socket | Yes: 3 ms median | No | No |
| Per-chat exclusivity | Structural: one object | Needs a D1 lease (`alternatives/lease.py`) because of redelivery and concurrency | Same |
| Documented cap on a turn's life in production | Object stays alive while it awaits fetches and timers (docs); no wall-clock cap while awaited | Consumer 15 min | **`waitUntil` extends up to 30 s after the response or disconnect** (Cloudflare limits page). A real model with tools can take longer. Local workerd does not enforce this: a 45 s turn finished |
| Code | `chat_core.py` + 130-line glue | Runner + lease + drive + queue handler + backend | Same |

Queue redelivery after a hard kill is unverified in production; only local workerd was used, where the message was lost. The `queue` and `waituntil` rows record what happened here, not what Cloudflare does.

The one thing a Durable Object gives up: a background task in an object is not formally guaranteed to survive if the platform evicts it while no request is in flight. The docs say timers and in-progress work keep it alive, and the crash test shows the alarm recovers a turn when it does not. That path was tested with SIGKILL, not with a real eviction.

## Measurements

Turn start (time from sending a message to `turn.started` reaching an SSE reader), median / p95, 8 chats each:

| runner | new chat (new object) | same chat, next turn |
|---|---|---|
| Durable Object | 63 / 120 ms | 175 / 402 ms |
| queue (`max_batch_timeout: 0`) | 70 / 279 ms | 68 / 288 ms |
| waitUntil | 83 / 110 ms | 109 / 312 ms |

The differences are inside the noise of one laptop. A new object costs nothing measurable here; a truly cold Worker isolate was not separated from it (see Snapshot).

Delivery (an event's stored timestamp to a client holding it), median / p95, about 40 streamed events each:

| transport | latency |
|---|---|
| WebSocket push from the object | **3 / 6 ms** |
| SSE polling D1 every 250 ms while busy (Durable Object host) | 154 / 259 ms |
| SSE polling, queue host / waitUntil host | 132 / 257 ms, 162 / 261 ms |

D1 read cost of tailing. Local D1 reports no `rows_read`, so this is counted, not billed:

- An SSE tab polls one indexed query every 250 ms while the chat is busy (4 per second) and every second when it is quiet, and ends after 55 s so the browser reconnects: about 220 D1 queries in a busy minute per tab, each returning zero rows when nothing happened. A 600 s A2A stream can make up to 2,400. The paid-plan subrequest limit is 10,000 per request.
- A WebSocket tab makes one read when it attaches and none after: events are pushed from the object, which wrote them. Idle sockets cost nothing while the object hibernates (duration is not billed during hibernation, per the docs).
- Writes are the same either way: about 8 D1 writes a second while a reply streams (150 ms coalescing).

Snapshot and start (`tools/snapshot-size.sh host`): the host Worker's startup snapshot is 45.4 MB raw, **12.13 MB gzip** (11.8 MB in the spike), so the object, the runner, the alternatives and the A2A views cost about 0.3 MB. The first request after a fresh start took 0.75 s. Python Durable Objects share the Worker's snapshot.

## WebSocket: is it worth it?

Yes, here. It cost one Python class using the hibernation API (`acceptWebSocket`, `webSocketMessage`, `webSocketClose`, attachments, auto ping/pong; all worked from a Python Worker), a 12-line upgrade gate and a ticket endpoint. It bought 3 ms delivery against 154 ms, no polling, one cursor protocol for every tab, and the payment webhook reaching a card by push while every relay call from the page was blocked (67 to 73 ms from webhook to receipt, `conformance/chat-cards.mjs`). A socket that slept through the object's hibernation for 25 s still received the push (`test_worker_socket.py`; whether workerd evicted the object in that window was not observed directly, but its state was reset between the early and late push in the spike).

SSE stays because A2A requires it, because a proxy or a browser can refuse a WebSocket (the page falls back after two failed opens, or with `?transport=sse`), and because it needs nothing but D1.

## Limits and what is not verified

- Nothing ran on Cloudflare. Production eviction, the 30 s `waitUntil` cap, queue redelivery, real D1 latency and billing, and real hibernation are documented or inferred, not observed.
- The crash test kills the whole local Worker. It does not exercise a deploy's rolling restart.
- Delivery latency was measured with client and server on one clock and one machine.
- Turn start numbers cannot separate a cold isolate from a warm one locally.
- The model was scripted. A real model's tool-call rate, `finish_reason` mix and turn length are unknown; `tools/real-model.sh probe` measures them.
