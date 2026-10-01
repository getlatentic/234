# Performance: startup, cold requests and the budget

Measured on 2026-10-01. **Local** means workerd through `pywrangler dev` with local D1 on one Apple Silicon laptop.
**Deployed** means throwaway probe Workers: copies of the public template (`host/wrangler.public.jsonc`) under other
names, on workers.dev, with dummy variables, a scratch D1 database and no secret of the real deployment. They were
deleted afterwards, and the real Workers were not touched. Wrangler reports "Worker Startup Time" at every deploy; the
numbers below use that report and requests made with curl from the same laptop (the round trip to the nearest
Cloudflare location is about 0.1 s of every deployed number).

The baseline is commit `918aa8d`, the tree before this work. "Now" is the tree this file is committed with.

## Three different things

A Python Worker is started three ways, and each is changed by different things.

| What | When | What it contains |
|---|---|---|
| **Deploy startup** (the "Worker Startup Time" wrangler prints) | at every deploy | Reading and compiling every module, then running its top level, once, to build the snapshot |
| **Cold start of an isolate** | the first request an isolate serves | Restoring the snapshot (memory image of the top level's result), then whatever the request imports or builds that the snapshot did not hold |
| **Warm request** | every other request | The request itself |

Importing a module at the top level costs deploy startup and snapshot size, and nothing at a cold start. Deferring an
import therefore makes a cold start slower, not faster: it moves the work from the snapshot to a request. The
measurements below show it (the 0.8 to 1.2 s that warming removed).

The clock stops inside a Worker (it advances only when the Worker waits for I/O), so Python cannot time its own
imports there. Import time was therefore taken natively (`python -X importtime`), heap was taken in the Worker with
`tracemalloc` (exclusive of what a module imports), and everything else from outside.

## The result

| | Baseline | Now |
|---|---|---|
| Startup snapshot, gzip (raw is 45,366,000 bytes in both) | 12,236,539 | **11,655,225** (-4.8%) |
| Local, restored snapshot: first `GET /`, median / p95 of 10 restores | 259 / 271 ms | **118 / 120 ms** |
| Local, restored snapshot: next `GET /` | 30 / 53 ms | 31 / 42 ms |
| Local, restored snapshot: first `GET /c/<id>/` after those | 57 / 60 ms | 58 / 60 ms |
| Local, warm `GET /`, median of 75 (a Worker that answers at once takes 4.0 ms) | 19.9 ms | **14.7 ms** |
| Local, warm `GET /c/<id>/`, median of 75 | 33.4 ms | 26.7 ms |
| Deployed startup, interleaved in the same hour, 5 deploys each | 3.14, 3.23, 3.36, 3.43, **6.39** s (median 3.36) | 2.05, 2.08, 2.13, 2.14, 2.80 s (**median 2.13**) |
| Deployed startup, every redeploy of the day (12 baseline, 9 now) | 3.14 to 6.39 s, median 3.49 | 1.99 to 2.80 s, median 2.13 |
| Deployed, first `GET /` after a deploy, 4 deploys each | 2.40, 1.33, 2.35, 1.46 s (median 1.9) | 1.18, 1.89, 1.64, 1.22 s (median 1.4) |
| Deployed, first POST of a new chat after a deploy | 3.75, 1.65, 3.71, 4.48 s (median 3.7) | 2.99, 2.81, 1.77, 2.72 s (median 2.8) |
| Deployed, cold `GET /` (the requests over 0.9 s, which are isolates starting), median per round of 40 requests, 3 rounds | 2.24, 1.49, 1.47 s | **1.38, 1.12, 1.17 s** |
| The same for a Worker that does nothing (the platform's floor) | 1.31, 0.98, 0.95 s | |
| Deployed, warm `GET /` (client round trip included) | 0.19 to 0.21 s | 0.19 to 0.23 s |
| Deployed, first message of a new chat (a new Durable Object), median of 12, 2 rounds | 1.91, 1.68 s | 1.79, 1.79 s |
| Deployed, the second message of that chat | 0.34, 0.33 s | 0.37, 0.35 s |

Goals and what was reached:

- *Startup below the 4.3 s of two deploys ago*: reached, 2.1 s against 3.4 s for the baseline measured at the same
  time. **The 7.65 s of the live Worker was not reproduced**; the probe of the baseline tree took 2.7 to 3.1 s in the
  morning, 3.1 to 5.6 s in the afternoon and once 6.4 s. Deploy startup varies by a factor of two over a day on the
  platform alone, and the baseline's tail is heavier than the new tree's, so a single deploy report says little. A
  probe with the sign-in variables set took the same 3.0 s; the real Worker's secrets and service binding add no
  module to the import.
- *Warm `GET /` under 150 ms locally*: it was already there (19.9 ms, 14.7 ms now); the 0.5 s once read as "warm" is an artefact
  of `tools/snapshot-size.sh`, which times its two requests while workerd is writing the snapshot (first 0.85 s and
  next 0.50 s on the baseline, 0.76 s and 0.49 s now, five runs each, spread under 0.05 s). On a restored snapshot the
  next request takes 30 ms. `tools/startup-budget.sh` times the restored snapshot.
- *Cold requests*: a deployed cold `GET /` is about 0.2 s above an empty Python Worker (the floor), against 0.5 s above
  before. Most of what remains is the platform. A new Durable Object (the first message of a new chat) costs about
  1.4 s more than a message to an existing one and is not changed by anything here; see "A separate Worker for the Durable Object".

## Where the startup goes

An empty Python Worker (workers SDK only): snapshot 6.89 MB gzip (31.5 MB raw), deploy startup 0.8 s, and a cold
request of about 1.0 to 1.4 s. That is the platform's floor. Importing Django and the host's settings, apps and
URLs adds 4.9 MB gzip and 1.8 s of deploy startup; what the host adds on top of Django (the turn runner, httpx, the
Durable Object) is 0.4 MB gzip and under 0.3 s.

Heap at the end of the imports, in the Worker (`tracemalloc`, MiB; modules in brackets):

| | Baseline | Now |
|---|---|---|
| Total | 14.05 (484) | 13.79 (515) |
| django | 7.44 (266) | 7.10 (262) |
| turns (the host's turn runner) | 1.22 (36) | 0.64 (36) |
| workers (the SDK) | 0.84 (12) | 0.83 (12) |
| email, httpx, sqlparse, http, urllib | 0.77, 0.79, 0.36, 0.29, 0.24 | 0.81, 0.80, 0.32, 0.29, 0.25 |

The modules are 515 now because the URL conf, the views and the templates' tags are imported at startup (see
"Changes"). `turns` shrank by an accounting effect more likely than a saving: the baseline billed `turns.compaction.scrub` 0.6 MiB
for six regular expressions, which looks like the process's first `IGNORECASE` compile being billed to the module that
ran it. The largest single modules are `workers.utils`
(0.63 MiB, the SDK), `django.db.models.expressions` and `.fields` (0.25 and 0.22), and `email._header_value_parser`
(0.21, imported by `http.client`). Natively, importing `config.wsgi` takes 0.67 s over 541 modules and no module is
above 19 ms of its own time, so there is no single module to remove; the cost is Django itself, spread flat.

## Where a warm request goes

Local, the Worker as deployed, median of 75 requests (a handler that answers at once takes 4.0 ms, curl and workerd
included):

| Request | Time | What is in it |
|---|---|---|
| `GET /manifest.webmanifest` | 4.7 ms | Django's middleware, cookie and a view with no template and no query: 0.7 ms over a Worker that answers at once |
| `GET /` | 14.7 ms | the same plus 1 query (the chat list) and the page's template |
| `GET /c/<id>/` | 26.7 ms | 3 queries (the chat, its events, the chat list) and the events' templates |

Natively the page is 2.0 ms and the chat 2.9 ms, and the profile splits the same way: 73% of `GET /` is rendering the
template, 23% of that is the 16 `{% url %}` calls; on the chat page rendering is 53% and the three queries 27%.
Django's system checks do not run in a Worker. Template compilation does not run per request: the cached loader keeps
compiled templates, which is why warming them at import is enough. D1 round trips cost one to three per page.

One cost was per request and is gone: the page read about 19 settings from the Worker's environment on every render,
each a call into JavaScript, 1.85 ms in total (measured by repeating the read 1000 times in a Worker). It is read
once per process now.

## Changes, and what each did

Every row is a change that stayed. Numbers are the ones measured when the change was made; the deployed ones are
from different hours, so only rows measured side by side compare.

| Change | Startup snapshot (gzip) | Local first `GET /` | Deployed |
|---|---|---|---|
| Baseline | 12,236,539 | 259 ms | startup 2.7 to 3.1 s (morning), cold `GET /` 1.5 to 2.2 s |
| Django 6.1.1 and its built-in `{% partialdef %}`; `django-template-partials` removed. That package's app imported `django.contrib.admin` (and with it auth, messages and the forms) at startup | 12,040,450 (-0.19 MB) | 260 ms | |
| Warm the URL conf, the views, the static helper, the context processors, the date formats and every template at import (`config/warm.py`, called from `index.py`); the snapshot holds them | 12,136,908 (+0.10 MB) | 137 ms | cold `GET /` median 2.35, 1.79, 1.95, 2.06 s (without) against 1.24, 1.05, 1.16, 1.12 s (with), four rounds measured in turn on two Workers |
| Ship the packages' bytecode (`compileall --invalidation-mode checked-hash`, in the build command) and do not upload translations and the contrib apps the host does not install (`python_modules.exclude`) | 11,626,511 (-0.51 MB) | 116 ms | startup 3.0 to 3.3 s without, 1.9 to 2.2 s with, deploys alternating on two Workers; upload 14.8 to 14.6 MB (the bytecode adds 6.9 MB, the exclusions take about as much) |
| Settings read once per process | | | warm `GET /` 20.0 to 17.2 ms, same harness before and after; the whole baseline to now is 19.9 to 14.7 ms without it |
| Connectors: a tool's JSON Schema is built once, not on every `tools/list` | | | 176 us natively per tool saved (about ten times that in WebAssembly) |

Why the bytecode helps: without it the Worker compiles the 500-odd modules it imports at every deploy, and the
snapshot is 0.5 MB smaller with bytecode, probably because the compiler's garbage no longer stays in it. Bytecode checked by the hash of its source cannot go stale,
so editing a module without rebuilding costs only a recompile. A pyc built by another minor version of Python is
ignored by the importer, so a runtime upgrade turns the gain off and does not break anything; the runtime is Python
3.14.2 (Pyodide 314.0.7) and the build uses the project's 3.14.5, whose bytecode format is the same. The local
`wrangler.jsonc` compiles only the packages, because `wrangler dev` watches `src/` and would rebuild for the bytecode
it had just written; the public template compiles both.

## Tried, and not kept

- **Optimised bytecode (`-OO`, no docstrings and asserts):** snapshot 11.37 MB against 11.63 (-0.25 MB), no change in
  latency, and it changes behaviour wherever a module reads `__doc__` or relies on `assert`. Not worth it.
- **Stubbing the imports Django does not need** (`argparse` through `sqlparse.cli`, `multiprocessing` and
  `statistics` through the SQLite backend `django-cf` builds on, `html.entities`, `difflib`): together about 1 MiB of
  heap, so under 0.1 s, for hacks on Django's import graph. Not done.
- **The same bytecode for the connectors:** deploy startup 1.96, 1.98 and 3.21 s without, 1.90, 1.56 and 1.88 s with,
  at +4 MB of upload. Too small to carry a second build step; their startup is pydantic, not compilation.
- **Lazy imports.** Deferring an import takes it out of the snapshot and puts it into a request; see the first
  section. The warm-up is the opposite move and is the one that won.
- **A request through the whole stack at import** (a fake WSGI call, to warm the middleware and the ORM as well): it
  hit an error without a database, grew the snapshot by 0.25 MB and did not speed the first request.
- **Django 6's built-in Content Security Policy** (`ContentSecurityPolicyMiddleware`, `SECURE_CSP`). It reads a
  static dict from the settings, while `chat/security.py` builds the page's policy at request time from the sandbox
  origin and the sign-in settings, and tests flip those per test. It drops a directive whose list is empty instead of
  emitting `'none'`, which would silently widen `frame-src` to `default-src`, and the nonce machinery it adds is
  unused here (no inline script). The host's own middleware is 12 lines; replacing it would need a lazy settings
  object that is the same code in another place. Not adopted.
- **Django's tasks framework:** the work that outlives a request runs in the Durable Object, which already is the
  single writer and the retry; nothing here needs a task backend.
- **Python 3.14:** deferred annotations are on by default and the code already uses the unparenthesised `except A, B`;
  the runtime offers no free threading and the other features (template strings, `compression.zstd`, interpreters)
  have no use in this code.
- **Pydantic features** (`TypeAdapter` reuse, strict modes, faster validation paths): the connectors validate with
  `Model.model_validate`, which already uses the compiled schema; a call takes 1.7 us natively on 2.12.5 and 1.5 us on
  2.14.0b2. Nothing to gain.

## A separate Worker for the Durable Object

The Durable Object and the page share one script, so a new chat's object restores the whole snapshot, Django included.
Two probes, one with only a Durable Object class and one with the whole host, then created 15 objects each behind a
warm Worker: median **1.30 and 1.35 s** (two rounds) for the small one against **1.50 s** for the host. Splitting the
object into a Worker of its own would save about 0.2 s of a 1.4 s cost and add a fourth Worker, a binding and a deploy
step. Not done. The cost is the platform's price of a new Python Durable Object; a message to an existing one takes
0.2 to 0.3 s.

One way to hide it would be to make the object exist before the person has finished typing: the home page mints the
chat's id, so it could ask for the object (a no-op call from `waitUntil`) as soon as it is shown. The numbers
do not support it. A second message sent 5, 15, 30 and 60 s after the first (three each, behind two GETs) took 0.29
s and 0.38 s once each, 1.05 to 1.43 s eight times, 2.9 s once and 16 s once: 10 of 12 took a second or more, 2 of 3 even at
5 s, because the request meets a cold Worker isolate about as often as a cold object. An object warmed in advance would not remove
that. Not built.

## Keeping a Worker warm with a Cron Trigger

Three probes of the full host had a Cron Trigger every minute: one that did nothing, one that fetched its own public
address, and one that called itself through a service binding. The runs were logged to D1 with the isolate that ran
them.

- The first run that was logged came **25 minutes after the deploy** of the version that logged it (an earlier version,
  deployed an hour before, could not be observed from outside, so a shorter delay is not excluded).
- From then on every run (10 of 10) was in **one isolate**, and the cron kept that isolate alive.
- A Worker that fetches its own workers.dev address gets **Cloudflare error 1042** (it answered 404 with that text);
  this is also what a deploy-time call to a fresh Worker's public address can hit. A service binding to itself works
  and reaches the isolate that is running.
- **External requests did not land in that isolate.** 25 requests at half-second intervals to each probe were
  served by 12 and 11 different isolates, and none was the cron's. Requests sent one per second meet a cold isolate
  on any Python Worker, an empty one included: between none and 43% of a round of 30 or 40, 20 to 35% in most rounds.
  The platform spreads the requests of one client over many isolates.

A cron can keep one isolate warm and a request will still miss it. It was not implemented. If a flag were wanted, it
costs one scheduled invocation a minute and, from these numbers, buys nothing a visitor could feel.

## After a deploy, and after being idle

First response of a deployed probe right after a deploy is in the result table above. Idle runs: three probes per
build for each kind of request, one request after 10, 30 and 60 minutes with no traffic at all, then two `GET /` at
once. The baseline's probes did `GET /` and then the first message of a new chat in turn; the new build's did each
kind on three probes of its own. The runs overlapped in time (12:56 to 16:16 and 15:58 to 17:28) but did not coincide.

| First request after | Baseline: median / max (3 probes) | Now: median / max (3 probes) |
|---|---|---|
| 10 min idle, `GET /` | 2.40 / 2.62 s | **1.40 / 1.89 s** |
| 30 min idle, `GET /` | 1.83 / 2.55 s | **1.41 / 1.87 s** |
| 60 min idle, `GET /` | 1.92 / 2.65 s | **1.27 / 1.56 s** |
| 10 min idle, first message of a new chat | 3.14 / 9.02 s | 3.16 / 3.52 s |
| 30 min idle, first message of a new chat | 4.04 / 4.37 s | 2.85 / 3.89 s |
| 60 min idle, first message of a new chat | 3.74 / 3.92 s | 3.33 / 3.79 s |
| The two `GET /` that follow each of those requests at once (36 each) | median 1.66 s, 83% over 1 s | median 1.26 s, 83% over 1 s |

How long a Worker sat idle did not matter: 10, 30 and 60 minutes read the same, and a cold isolate is what a request
normally meets. The two requests made at once after each idle request were slow in 83% of cases for both builds,
because each of them landed on another new isolate; a Worker without traffic has no warm isolate to reuse, and one
with a little traffic still has many cold ones (see the cron measurement). The new build is faster by what the warm-up
and the bytecode took out (about 0.4 to 1.0 s of a cold `GET /`), and the first message of a new chat stays about 3 s
after idle: a cold Worker isolate plus a new Durable Object plus the writes.

A brand-new Worker's address answers **404 for about a minute** after its first deploy while the route spreads; a
redeploy of an existing Worker does not.

## The home page as a static asset

`GET /` is no longer a request to the Worker. `build_shell` renders the empty home once at build time into
`staticfiles/index.html` (with a `_headers` file), Workers static assets serve it from the edge, and what is the
visitor's (the CSRF token, the chats, the account) comes from `GET /api/me`, which the page asks for when it loads
([chat-ui.md](chat-ui.md#the-home-is-a-static-page) has the contract and the headers). The assets config is
`"assets": {"directory": "./staticfiles", "html_handling": "auto-trailing-slash", "not_found_handling": "none"}` with
`run_worker_first` left at its default: a path that has an asset (`/`, `/static/...`) is answered by the platform,
every other path (`/c/...`, `/auth/...`, `/hooks/...`, `/join/...`, `/memory/...`, `/ops/...`, `/a2a`, `/api/me`, the
manifest) has none and reaches the Worker. `/index.html` redirects to `/`.

**Measured on 2026-10-01** on four throwaway probes of the public template (two of the tree before this change,
`ea08695`, two of this one), one Cloudflare location (Frankfurt) and the same laptop, deleted afterwards; the real Workers
were not touched. Curl opens a new connection for every request; the browser is Chromium with a new context for every load.

| | Before: Django renders `/` | After: static `/` and `/api/me` |
|---|---|---|
| Worker invocations for six `GET /` (`wrangler tail`) | six | **none** (only `/api/me` and `/c/<id>/` were seen) |
| Warm `GET /`, curl, 60 requests: first byte (of it, after the TLS handshake) | 247 ms (189) | **112 ms (52)** |
| Warm `GET /api/me`, 60 requests | | 233 ms (173) |
| Cold `GET /` (after 12 to 13 minutes with no traffic; the first request of each of 3 rounds on 2 probes) | **1.24, 1.27, 1.79 s** curl; 1.37 and 1.60 s browser first byte (a sixth request met a warm isolate: 0.38 s) | **0.095, 0.100, 0.105 s**: a static asset has no cold start |
| Cold `GET /api/me` (same rounds) | | 1.13, 1.18, 2.07 s curl; the page's own call, 2.6 and 2.8 s from navigation start |
| Browser, until the composer exists and takes typing, warm, 15 loads each, interleaved: median (range) | 820 ms (522 to 2953) | **547 ms (464 to 677)** |
| The same, the loads that met a cold Worker | 1.77 and 2.05 s | 0.65 to 1.04 s |
| Local, warm, median of 75: `GET /` / `GET /api/me` | 14.7 ms | **1.9 ms** / 12.0 ms |

What this says. The home no longer waits for Python: the first byte is the platform's (about 0.1 s with a new
connection), it does not depend on how long the Worker has been idle, and the time to a usable composer no longer has the
tail the cold Worker gave it (the "before" loads over 1.4 s are isolates starting; the "after" loads stay within 0.2 s of
each other). The cold start did not go away: it moved to `/api/me`, which the page asks for in the background. On a cold
Worker the chat list, the account and the chats button arrive 1.1 to 2.1 s after load (about 0.2 s on a warm one), the
composer and the starters are usable before that, and a first message sent in that time waits for the token. Someone who
reads the page before sending has paid the cold start by then.

A probe was not a real deployment: it had no secrets, no service binding, and a model that was not set, so the composer
is turned off by `/api/me` (`problem`) a moment after load in these runs; the real Worker's `/api/me` also asks the
database for the chat list, as these did. The numbers of one afternoon on one connection vary by the factor the
sections above found for the platform, so read them for size, not for the digit.

`tools/startup-budget.sh` now times `GET /api/me` on the restored snapshot, because `/` is not served by the Worker:
first request 0.11 s, next 0.022 s; the snapshot is 11,681,729 bytes gzip (11,655,225 before; the budget is
12,240,000).

## Versions

| Package | Now | Newest | Where it stops |
|---|---|---|---|
| Django (host) | **6.1.1** | 6.1.1 | nothing: 820 unit tests, the Worker suites on the local stack and the browser suites pass |
| Django (connectors' development group, `card/build.py` renders the cards with it) | **6.1.1** | 6.1.1 | nothing |
| django-cf | 0.2.16 | 0.2.16 | nothing; its classifiers stop at Django 5.0 but it needs only the SQLite backend classes, and D1 reads and writes work on 6.1.1 |
| pydantic (connectors) | **2.12.5** with pydantic-core 2.41.5 | 2.13.5 stable, 2.14.0b2 | see below |
| httpx, asgiref, sqlparse, tzdata | as locked | | |

The Python Workers runtime for `compatibility_date` 2026-09-21 is Pyodide 314.0.7 (Python 3.14.2, ABI
`pyemscripten_2026_0`). It offers pydantic 2.12.5 and pydantic-core **2.41.5**, httpx 0.28.1 and tzdata 2025.3, and no
Django. pydantic-core is a native extension, so a wheel for WebAssembly must exist.

- **pydantic 2.13.5 cannot be used.** It requires `pydantic-core==2.46.5`, which has no WebAssembly wheel (PyPI has
  them for 2.47, 2.48 and 2.49 only). `uv lock` resolves it; `uv run pywrangler sync` then stops with: "Because
  pydantic-core==2.46.5 has no usable wheels and pydantic==2.13.5 depends on pydantic-core==2.46.5, we can conclude
  that pydantic==2.13.5 cannot be used", and the hint that wheels are required because building from source is
  disabled.
- **pydantic 2.14.0b2 works** with pydantic-core 2.49.0 (a `cp314-pyemscripten_2026_0_wasm32` wheel from PyPI): it
  loads in the Worker, `tools/list` and an invalid `tools/call` answer correctly on a local Worker, and the 1,223
  connector tests pass natively. It is a beta in the payment connectors, so it is not adopted. When 2.14.0 is out,
  changing `pydantic>=2.12,<2.13` in `checkout/pyproject.toml` and running `uv lock` and `uv run pywrangler sync` is
  the whole upgrade; Dependabot is told to skip 2.13 in `.github/dependabot.yml` and will then offer 2.14.

### The three Dependabot pull requests

Their CI runs did not fail on the code: the jobs never started ("The job was not started because recent account
payments have failed or your spending limit needs to be increased", on all six runs). Run locally, with what each
changes:

- **#3, Django 5.2.17 to 6.1.1 in /host:** main now has this (commit "The host runs on Django 6.1…"), with the template
  change it needs. The pull request's own `pyproject.toml` and lock edits conflict with main's; close it as done.
- **#1, Django in /checkout:** main follows (commit "The connectors' card build runs on Django 6.1"); close it as done.
- **#2, pydantic 2.12.5 to 2.13.5 in /checkout:** cannot be merged, for the reason above. Close it; the ignore rule
  keeps it from coming back until 2.14.

## The budget

`tools/startup-budget.sh` saves the host's startup snapshot the way a deploy does, fails when its gzip size is over
`BUDGET_GZIP_BYTES` (**12,240,000**, 5% over the 11,655,225 above), restores it three times and prints the first and
next `GET /api/me` on the restored snapshot (the home page is a static asset: about 0.11 s and 0.02 s now). `tools/check.sh` runs it once, before the stacks
come up. It uses ports `PORT_BASE+18` and `+19` and takes about 45 s. When it fails, find what grew the snapshot
(`tracemalloc` by module, as in "Where the startup goes") before raising the number; the deployed cap is not published
and was measured near 18.5 to 19.7 MB elsewhere.

Reproducing: `tools/startup-budget.sh` (snapshot and restored requests), `tools/snapshot-size.sh host` (the old,
save-mode timings), `npx wrangler deploy -c <a rendered public template under another name>` for the deploy startup.

## What is not verified

- The real Worker's deploy startup after these changes: only probes were deployed, and the lead's 7.65 s was not
  reproduced on one.
- Idle behaviour of the real Worker, as opposed to the probes (same code, same snapshot, but no secrets and no service
  binding).
- That a production runtime moved to a Python 3.15 would still accept the bytecode (it will recompile if not).
