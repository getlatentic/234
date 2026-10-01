# Deploying to Cloudflare

Three Workers and two D1 databases on your Cloudflare account, reachable on workers.dev. Every name lives in the
first lines of [`tools/deploy.sh`](../tools/deploy.sh) and nowhere else; the wrangler files
(`sandbox/wrangler.public.jsonc`, `host/wrangler.public.jsonc`, `checkout/wrangler.public.jsonc`) are templates that
the script fills in. The live demo (https://ask234.wintern.workers.dev) is one such deployment.

## Before the first deploy

- A Cloudflare account on a plan that runs Python Workers and Durable Objects, and `npx wrangler login` once.
- Your account's workers.dev subdomain, in the variable `SUBDOMAIN`. Put it in the untracked file
  `.env.deploy.local` at the repository root (`SUBDOMAIN=<your-subdomain>`) or in the environment. Any other name
  below can be set the same way.
- `tools/deploy.sh init` creates the two databases; `tools/deploy.sh names` prints what is deployed and where.

| | Default name | Address |
|---|---|---|
| Card sandbox (frames every card; static, no state) | `ask234-sandbox` | `https://ask234-sandbox.<your-subdomain>.workers.dev` |
| Chat host (the page, A2A off) | `ask234` | `https://ask234.<your-subdomain>.workers.dev` |
| Connectors (four MCP servers, the simulated checkout page) | `ask234-connectors` | `https://ask234-connectors.<your-subdomain>.workers.dev` |
| Host database (chats, the event log, model-call counts) | `ask234-host-db` | |
| Ledger database (quotes, limits, simulators) | `ask234-ledger` | |

A Worker name is also its address. The ids of the databases and the rate-limit namespace (`RATE_LIMIT_NAMESPACE`,
which must not clash with another Worker on your account) are filled into the templates; the deployed copies
(`*/wrangler.deploy.jsonc`) are ignored by git.

## The card sandbox

The chat page does not run a connector's card itself. It frames the card behind a **sandbox proxy** served by the
third Worker, from another origin, as the MCP Apps standard requires of a web host; what that means, and what the
standard asks and this does, is in [mcp-apps-compliance.md](mcp-apps-compliance.md).

- **The Worker** (`sandbox/`, JavaScript, no dependencies, no binding, no database, no cookie; one secret, `SIGNING_KEY`) answers
  `GET /` (the proxy page), `GET /view` (the page a card is written into, with the card's policy in its headers) and
  `GET /health`. It answers a page only for the host's origin, named in its variable `HOST_ORIGINS` (the host's own
  address, filled in from the names in `tools/deploy.sh`), and `frame-ancestors` is that origin alone.
- **The host's setting** is `SANDBOX_ORIGIN` (a variable of the host Worker, `https://ask234-sandbox.<your-subdomain>.workers.dev`
  in `host/wrangler.public.jsonc`, filled in from the same names). The host's page policy allows frames from that
  origin and no other, and a card cannot be shown without it (the page says "This card could not be shown"). The host
  refuses to start with a `SANDBOX_ORIGIN` equal to its own address.
- **Deploy.** `tools/deploy.sh` deploys the sandbox first, then the connectors and the host. `tools/deploy.sh upload
  sandbox` uploads it alone. Its checks (`node --test sandbox/test/*.test.mjs`) run before every deploy.
- **Smoke test** (`tools/deploy.sh`, curl only, part of every deploy): the sandbox's `/health` is 200; the proxy page
  for the host is 200 and names the host as its only embedder (`frame-ancestors`); a page that names any other host is
  refused (403); the view's policy is the specification's default; a view under a policy the host did not sign is refused (403); the sandbox sets no cookie; the host's page
  allows frames from the sandbox's origin; none of the host's cookies names a `Domain`.
- **Roll back** the sandbox alone: `tools/deploy.sh rollback sandbox`. It restores the earlier proxy; nothing in it is
  data. The host and the sandbox agree only on the messages of the standard, so either can be rolled back without the
  other, except that a host from before the sandbox existed does not use it and a sandbox with the wrong
  `HOST_ORIGINS` refuses the host (cards then read "could not be shown").
- **Delete** it with `tools/deploy.sh destroy` (all three Workers and both databases), or alone with
  `npx wrangler delete <sandbox-worker>`; the host then shows no card until the setting is removed and the sandbox is
  back.
- **Logs:** `tools/deploy.sh tail sandbox`. A view whose declaration was narrowed leaves a `csp.refused` line there,
  and the host's log has `card.csp` and `card.csp.refused` lines for what each card asked and got.
- **One site.** The sandbox is another origin on another hostname, and on workers.dev it is still the same *site* as
  the host (workers.dev is a public suffix): the host's cookies are host-only, which keeps them from it. A different
  site needs a custom domain for the sandbox: set `SANDBOX_ORIGIN` and the sandbox's `HOST_ORIGINS` to match.
- **Paystack's popup** is on by default (`INLINE_PAYSTACK`, a variable of the host and of the connectors) and does
  nothing in this deployment: it applies only where the connectors run in Paystack test mode with a key, which the
  public deployment never does. No card declares an external origin here, so no visitor sees a line about one.

## What a visitor can and cannot do

- **No real money and no provider call.** All four connectors run their simulators (`PAYSTACK_MODE`,
  `PAYSTACK_PAY_MODE`, `SEND_MONEY_MODE`, `AIRTIME_MODE`, `FOOD_ORDER_MODE`, `VTPASS_MODE` are `simulated`).
  A Paystack test key or VTpass credentials set by mistake change nothing, and a live key (`sk_live_`) or
  `VTPASS_MODE=live` stops the connectors at startup. These rules are tests (`checkout/tests/test_public_config.py`,
  `test_config.py`), which `tools/deploy.sh` runs before every deploy. Never put a Paystack or VTpass key on these Workers.
- **The simulated VTpass delivers to any valid Nigerian mobile number**, so a visitor who pays with their own
  number gets a receipt (nothing reaches the phone). `201000000000` stays pending and `100000000000` fails, to
  show those cards. The real VTpass sandbox does not work like this: the connectors' own tests cover what the real sandbox does differently.
- **Each visitor has a daily allowance of their own:** ₦100,000 a day and ₦50,000 a payment, for each visitor,
  not one total for everybody (`DAILY_LIMIT_KOBO`, `PER_PAYMENT_LIMIT_KOBO`, unchanged). The host names the
  visitor's id to the connectors on every tool call, in the header `x-ledger-owner`, and the ledger scopes every
  quote, approval and limit by it. The connectors refuse a tool call that names no owner (`REQUIRE_OWNER=1`,
  a test of the public template), so an unlabelled call is never pooled with anyone's. A visitor who reaches
  their limit reads one line, with what is left of their own day. **Clearing cookies makes a new visitor with a
  new allowance** (a person who signs in with Google has an allowance of their account's, the same on every device: [auth.md](auth.md)). That is acceptable here because the money is simulated, and the global and per-visitor model
  caps and the rate limit, which are unchanged, are what bound abuse by clearing cookies. A deployment that
  moves real money must tie the allowance to an authenticated account instead.
- **The connectors' tools answer only to the host.** `/<connector>/mcp` needs `Authorization: Bearer` with the shared
  token (`MCP_ACCESS_TOKEN` on the connectors, `CHECKOUT_MCP_TOKEN` on the host); without it the answer is 401
  before anything is read, and the Worker refuses to start if the token is missing (`REQUIRE_MCP_TOKEN`).
  The owner header is read only after that, and only from the host's request: the connectors take the owner from
  that header and from nothing a browser, a card or the model sends.
  The host calls the connectors through a **service binding**, not the public address: a Worker cannot fetch another
  Worker of the same account by its workers.dev address (measured: the connector answered the host's request with
  404). The connectors call the host's payment hook the same way (binding `HOST`, `PAYMENT_WEBHOOK_URL`); the host
  must already exist when the connectors are deployed, and a failed call only means the card updates by polling.
  What stays public on the connectors is `/health` and the simulated checkout page `/sim/checkout/<reference>`,
  which a person opens from a card and which only moves simulated state. `/test/*` is off.
- **Model spend is capped:** 300 calls a day for everyone, 30 for each visitor (D1 counters, one conditional
  `UPDATE` each), 12 messages a minute per visitor per Cloudflare location, 500 characters a message. To see the
  count: `tools/deploy.sh tail host` shows refusals; the counters are in `chat_budget` of the host database.
- **The model's settings are secrets** (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`), not variables. Until they are
  set a message is answered with one plain line, "No model is configured. Set LLM_BASE_URL and LLM_API_KEY."

## Sign in with Google (optional, off until the file exists)

The site works without it. To turn it on, make the Firebase project's console steps ([auth.md](auth.md#what-you-do-in-the-console)) and writes the three public identifiers of the project's web app in an **untracked** file at the repository root, `.env.auth.local` (git ignores it: `.env.*` and a line of its own in `.gitignore`):

```
FIREBASE_PROJECT_ID=<your-firebase-project-id>
FIREBASE_API_KEY=<the web app's apiKey, from the console's "Add app" page>
FIREBASE_AUTH_DOMAIN=<your-firebase-project-id>.firebaseapp.com
```

One `NAME=value` a line; blank lines and lines starting with `#` are ignored; one pair of quotes around a value is removed; nothing else in the file is read. `tools/deploy.sh` never prints a value.

- **No file:** the deploy leaves sign-in off ("sign-in with Google: off"), and its smoke test checks that there is no button, that `/auth/session` answers 404 and that the opener policy is `same-origin`.
- **A file with a value missing or malformed:** the deploy stops before anything is uploaded and names the variable (`FIREBASE_API_KEY(missing)`), so sign-in is never half on.
- **A complete file:** `render` replaces the marker line in `host/wrangler.public.jsonc` with the three values as Worker **variables** (they are identifiers, not secrets), and the deploy generates the host's secret `ACCOUNT_KEY` with `openssl` once and keeps it (it is the key that turns a Firebase uid into an owner: rotating it would orphan every account's chats, so `tools/deploy.sh rotate` does not offer it). `tools/deploy.sh upload host` does the same. The smoke test then checks that the drawer offers Google, that `/auth/session` refuses a garbage token with **401**, that it refuses a post without the CSRF token with 403, that the opener policy is `same-origin-allow-popups` and that only `apis.google.com` is added to `script-src`.
- **`tools/deploy.sh auth`** says, by name, whether each of the three is set and well-formed and whether the host already has `ACCOUNT_KEY` (it lists the host's secret names, read only); it prints no value and uploads nothing.
- **Turning it off** is removing the file and deploying: the variables go, the button goes, sessions already issued stop being read (the middleware ignores the cookie when sign-in is off). `ACCOUNT_KEY` stays, so turning it on again finds every account's chats where they were.
- **What changes on a deploy that turns it on:** the page policy gains the four entries of [auth.md](auth.md#policy-and-opener-what-sign-in-adds), the chats button is shown on the empty home (the drawer is the only place to sign in), and an anonymous visitor who signs in has their chats moved to their account. A host configuration that sets `FIREBASE_AUTH_EMULATOR_HOST` or `FIREBASE_KEYS_URL` does not start outside development, and the public template sets neither.

## Set the model (once)

The model is any OpenAI-compatible chat endpoint. Each line reads one value out of the untracked `.env.local` at
the repository root and sends it to Cloudflare; the value is never printed, and the script refuses an empty
value. If your file names them differently, change the pattern.

```
grep '^LLM_BASE_URL=' "$PWD/.env.local" | cut -d= -f2- | tools/deploy.sh secret host LLM_BASE_URL
grep '^LLM_MODEL=' "$PWD/.env.local" | cut -d= -f2- | tools/deploy.sh secret host LLM_MODEL
grep '^LLM_API_KEY=' "$PWD/.env.local" | cut -d= -f2- | tools/deploy.sh secret host LLM_API_KEY
```

Not in the `.env`? For the two values that are not keys, type them in place of the `grep`:

```
printf %s 'https://YOUR-ENDPOINT/v1' | tools/deploy.sh secret host LLM_BASE_URL
```

`tools/deploy.sh secret host NAME` is `wrangler secret put NAME --name <host-worker>` with those checks. The change is live
within seconds and needs no redeploy. To try it: open the host address, start a chat, ask for a payment.

## Secrets that were generated (never shown, never in git)

| Secret | On | Used for | Rotate |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | host | the visitor cookie, share links and socket tickets | `tools/deploy.sh rotate DJANGO_SECRET_KEY` (every visitor becomes a new visitor) |
| `WEBHOOK_SECRET` | host and connectors (one value) | the connectors sign `POST /hooks/payment` when the simulated checkout records a payment; the host verifies | `tools/deploy.sh rotate WEBHOOK_SECRET` (sets both, uploads both) |
| `OPS_TOKEN` | host | `/ops/migrate/` | a new one on every deploy; it exists only for the length of the deploy |
| `CHECKOUT_MCP_TOKEN` and `MCP_ACCESS_TOKEN` | host and connectors | the bearer token between them (one value) | `tools/deploy.sh rotate token` |
| `SANDBOX_SIGNING_KEY` (host) and `SIGNING_KEY` (sandbox), one value | host and sandbox | the host signs the policy of each card's view; the sandbox serves a view only under a signed policy | `tools/deploy.sh rotate SANDBOX_SIGNING_KEY` (sets both; no upload needed, cards open correctly from the next page load) |
| `APPROVAL_SECRET` | connectors | signs approval tokens | `tools/deploy.sh rotate APPROVAL_SECRET` (quotes waiting for approval stop working) |
| `ACCOUNT_KEY` | host, only when sign-in is on | the key of a signed-in person's owner (an HMAC of their Firebase uid) | never: a new key would leave every account's chats under owners nobody can derive. Rotating `DJANGO_SECRET_KEY` signs everyone out but keeps their chats |

Two things about rotating, both measured on 2026-09-29:
- `rotate token` sets the two Workers one after the other, so for a few seconds the host's calls to the connectors
  are refused (one request in a poll every 3 s); then it is fine, with no new version.
- The host's Django settings are read once, when a version starts, and a secret changed alone does not reach them:
  a rotated token did not reach the host until the host read it when first needed (`chat/backend.py`), which is why
  `rotate DJANGO_SECRET_KEY` and `rotate WEBHOOK_SECRET` upload the host again as part of the command. The model's
  `LLM_*` secrets are read on each request and need nothing.

`A2A_TOKENS` is not set, so no other agent can call the A2A endpoint. To allow one:
`openssl rand -hex 32 | sed 's/^/partner:/' | npx wrangler secret put A2A_TOKENS --name <host-worker>`.

## Redeploy

```
tools/deploy.sh
```

It refuses when the working tree has uncommitted changes. Then it runs `ruff` and the unit tests of both projects
(including the public-configuration tests) and the sandbox's, deploys the sandbox, applies the ledger migrations,
deploys the connectors, deploys the host (which runs Django's migrations inside the Worker), and smoke-tests the three
addresses with curl. It sends one word
to a fresh chat, so once a model is set a deploy makes one model call. `CHECK_FULL=1 tools/deploy.sh` also runs `tools/check.sh` first
(fifteen minutes, ports 8900-8999).

It is safe to run again: secrets that exist are kept and migrations already applied are skipped.

**The ledger migration `0005_memory.sql`** (the tables of what 234 remembers, with an FTS5 index and its triggers, [memory.md](memory.md)) is applied by the same step. It creates tables only and changes no row of the ledger. The memory settings (`MEMORY_INDEX_TOKENS`, `MEMORY_MAX_ENTRIES`, `MEMORY_MAX_BODY_BYTES`, `MEMORY_RETENTION_DAYS`, `MEMORY_PROPOSAL_TTL_SECONDS`, `MEMORY_MAX_PENDING`) have defaults and are not set by the deploy. It has not been run on the real D1: FTS5 and its triggers ran on the local D1 engine only. The host offers memory when `memory` is in `CONNECTORS` (the default), and only to a signed-in account.

**The ledger migration `0004_owner.sql`** (each quote gets an owner) is applied by this same command, in the
"ledger migrations" step, before the connectors are uploaded: `wrangler d1 migrations apply DB --remote`. It is
safe with data present: it adds a column with a default (`ALTER TABLE ... ADD COLUMN`, no table rebuild), an
index, and recreates one trigger; existing rows keep everything and take the owner `legacy`, which no caller
can present. Run on the local D1 engine over a ledger with quotes, events and simulator rows it kept them all.
It has not been run on the real D1. What the deploy does to what is already there:
- a quote that is open or approved when the deploy happens is no longer visible to its visitor (its card says
  the quote was not found); quotes that were finished are unaffected, and no quote of an earlier day counted
  against today anyway;
- nobody's day starts with earlier spend: `legacy` rows count toward no visitor;
- between the connectors' upload and the host's, for a few seconds, the old host's tool calls are refused
  (they carry no owner); the deploy runs them one after the other and its smoke test comes last.
`tools/deploy.sh upload host` (or `connectors`, or `sandbox`) uploads the committed code again with no checks and no migrations.

## Roll back

```
tools/deploy.sh versions host          # the recent versions of the host, newest first
tools/deploy.sh rollback host          # back to the previous version; add a reason as the third word
tools/deploy.sh rollback connectors
tools/deploy.sh rollback sandbox
```

A rollback restores code, variables and secrets as they were in that version. It does not undo a D1 migration or
delete rows. After `0004` the `owner` column stays; the earlier connectors ignore it and their new quotes take the
owner `legacy`, so they still work against the migrated ledger. Roll the host and the connectors back together:
the earlier host names no owner, and the current connectors refuse a tool call without one. The Durable Object class migration (`v1`) is never rolled back.

## Logs

```
tools/deploy.sh tail host
tools/deploy.sh tail connectors
tools/deploy.sh tail sandbox
```

All three Workers have observability on, so logs are also in the Cloudflare dashboard under each Worker.

## Delete everything

```
tools/deploy.sh destroy
```

It asks you to type the host's name, then deletes the three Workers (with the Durable Object data) and both databases.
It deletes nothing else. Check with `npx wrangler d1 list` and the Workers list in the dashboard.

## Rename

A Worker's address cannot be renamed, so a rename is a new Worker and the old one deleted.

1. Edit the names at the top of `tools/deploy.sh` (`HOST_WORKER`, `CONNECTORS_WORKER`, `SANDBOX_WORKER`, `HOST_DB`, `LEDGER_DB`).
2. `tools/deploy.sh init` creates the new databases, `tools/deploy.sh` deploys under the new names (new secrets are
   generated; run the three model commands above again).
3. Delete the old ones: `HOST_WORKER=old-host CONNECTORS_WORKER=old-connectors SANDBOX_WORKER=old-sandbox HOST_DB=old-host-db LEDGER_DB=old-ledger tools/deploy.sh destroy`.

Chats and the ledger do not move: they are demo data.

## Measured

- Startup snapshot, gzip (Cloudflare's limit is unpublished; it was measured near 19.7 MB elsewhere): connectors 10.80 MB
  (raw 45.4 MB), host 12.12 MB (raw 45.4 MB), by `tools/snapshot-size.sh`.
- Upload: connectors 7.3 MiB (1.98 gzip), host 14.3 MiB (3.5 gzip). Both deployed on the first try, and again
  every time after; no size or startup-snapshot refusal happened.
- Wrangler's own report of startup time at deploy: connectors 2.5 to 2.7 s, host 4.3 to 7.4 s.
- Checked with curl on the public addresses: the page, a chat created, a message answered with the one plain
  "No model is configured" line (a Durable Object ran the turn and wrote to D1), the event stream, a WebSocket
  upgrade (101; 403 from a foreign origin), the card served through the binding, the connectors' 401 without or
  with a wrong token, `/test/*` and `/ops/migrate/` closed, an unsigned payment hook and an A2A call refused.

## Not verified

- **Sign-in with Google on Cloudflare and with real Google and Firebase** (all of it ran against the Firebase Auth emulator; see [auth.md](auth.md)), and the deploy script's new lines: `tools/deploy.sh auth`'s parsing and the marker's replacement were run offline against a scratch copy, and the smoke checks for it were not run, because nothing was deployed.
- Migration `0004` on the real D1, and the owner header through the real service binding between the two Workers
  (both were run locally only: the migration on the local D1 engine over existing rows, the header through a
  fake binding in a unit test and over localhost in the browser runs).

- No model call was made by the deploy checks beyond the one smoke-test word.
- No card was rendered in Claude Desktop or ChatGPT.
- **The sandbox Worker was not deployed.** It runs in workerd on the local stack (its headers and the proxy's
  behaviour are checked in Chromium and WebKit), and the deploy step, its smoke test and its rollback are written and
  were not run. The connectors' new answers to the stateless era of MCP, the `Origin` refusal and the popup's
  `_meta` are likewise checked locally only.
- The Durable Object path (eviction, hibernation, the WebSocket at the edge) was checked only as far as the smoke
  test reaches: see `docs/durable-chat.md`.
- The rate limiter counts per Cloudflare location; it slows a burst but is not a hard cap. The daily model-call
  caps are the hard cap.
