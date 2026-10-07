# 234 in other agents

Any MCP client can use 234's connectors: Claude, ChatGPT, Cursor, VS Code, or your own agent. The client signs in with OAuth, the person approves the client once on a 234 page, and every payment still waits for the person on a card.

## Install the plugin

`plugins/234` is an [Agent Plugins 1.0.0](https://agent-plugins.org/) package:

| File | What it holds |
|---|---|
| `plugin.json` | The manifest: name `234`, version, licence |
| `mcp.json` | Five Streamable HTTP servers at `https://234.getlatentic.com/mcp/<connector>`: `airtime`, `send-money`, `food-order`, `paystack-pay`, `memory` |
| `skills/pay-with-234/SKILL.md` | How an agent quotes, hands the person the card and reports the outcome |

The package holds no secret. Each server asks the client to sign in the first time it is used.

## What a client goes through

1. It calls `/mcp/<connector>` with no token. The answer is `401` with `WWW-Authenticate: Bearer resource_metadata="…", scope="payments"` (`memory` for the memory server).
2. It reads the protected resource metadata (RFC 9728) and then `/.well-known/oauth-authorization-server` (RFC 8414).
3. It registers (RFC 7591, `/oauth/register`) or names its client metadata document by URL as its `client_id`. Only public clients: `token_endpoint_auth_method` is `none`.
4. It sends the person to `/oauth/authorize` with PKCE S256 and `resource` set to the server's URL. The person signs in with Google if needed, and presses Allow. The page names the client, what it can do, and the host it returns to.
5. It exchanges the code at `/oauth/token`: an access token for one hour and a refresh token for 30 days.
6. It calls `/mcp/<connector>` with `Authorization: Bearer …`. The gateway passes the MCP message to the connector as the account that approved the client.

## The rules the server enforces

| Rule | Where |
|---|---|
| A code works once, within 60 seconds, with its own PKCE verifier, client, redirect URI and resource | `host/src/oauth/grants.py` |
| A token opens one connector, the one named in `resource`; any other answers `401` | `host/src/oauth/gateway.py` |
| A refresh token works once. Using one twice ends every token of its grant. | `grants.refresh` |
| `/oauth/revoke` on either token ends the grant | `grants.revoke` |
| The database keeps SHA-256 digests of codes and tokens, never the values | `host/src/oauth/models.py` |
| A redirect URI is HTTPS, or HTTP on the loopback (any port). An unknown client or redirect URI gets an error page and is never redirected to. | `host/src/oauth/redirects.py`, `requests.py` |
| A client metadata document is fetched only from an HTTPS URL with a path on a host name (no address, no localhost), at most 10 KB, no redirect followed, and kept for a day | `host/src/oauth/clients.py` |
| The gateway passes on only `mcp-protocol-version`, `mcp-session-id` and `last-event-id`. The owner header and the connector token are the host's own. | `gateway.py`, `turns/hub.py` |
| The consent form needs the page's CSRF token. The page's `form-action` names only itself and the client's redirect origin. | `views.py` |
| Registration is rate limited per address, and consent per account. The token endpoint is not rate limited: Claude's and ChatGPT's servers refresh for all their users from a few addresses, and a code or token is 256 random bits. | `views.py` |
| A code is taken, and a refresh token claimed, by one statement whose returned rows say it ran. On D1, Django's row counts are not rows changed (a write that touches nothing reports -1), and the host tests make every count -1 to keep it that way. | `config/sql.py`, `tests/conftest.py` |
| Everything is `404` while sign-in is off | `views.signing_in` |

Tests: `host/tests/test_oauth.py` (46 cases, run with SQLite refusing `SELECT … FOR UPDATE` as D1 does). `conformance/mcp-oauth.mjs` runs the whole flow with the official TypeScript MCP client and a real browser against the Firebase Auth emulator. Two accounts each approve a client, and one account cannot see the other's quote.

A person sees the clients they allowed under Connected apps in the chats drawer, with the connectors each opens, and Disconnect deletes every token that client holds for them ([pact.md](pact.md#delegated-acting-as-the-persons-account)). A grant also ends when the client revokes it or after 30 days without a refresh.

**Not done:** custom URI schemes for native apps (`cursor://…`) are refused, because the MCP authorization spec allows only HTTPS and loopback redirects.

## The outcome in the conversation

In Claude or ChatGPT, a card whose quote ends (delivered, declined, failed, expired) sends the outcome as a `ui/message`, so the model answers at once instead of waiting to be asked. It does this only for an ending it saw happen: a press of its own button or a live status read. A reloaded conversation shows each card again from its old result. The card then asks the server once how the quote stands, and posts nothing again. In 234's own chat (host `checkout-host`), the host writes the outcome into the thread itself, so the card only updates the model's context. Checked in `conformance/card-outcome-hosts.mjs`, with hosts built on the official ext-apps `AppBridge`.

## How an ending travels

```
Paystack / VTpass ──webhook──▶ connectors /hooks/paystack (signature) · /hooks/vtpass (a hint only)
                                  │ answer at once, queue "check quote X again"       [PROVIDER_JOBS]
                                  ▼
                       recheck as the quote's owner: verify / requery with the provider
                                  │ the quote ends: an UPDATE of its state
                                  ▼
                       trigger quote_finished → outbox row per subscription (same statement)
                                  │ handed on after the request and every minute      [EVENT_JOBS]
                                  ▼
                       signed delivery (Standard Webhooks), retried with backoff, then dead-lettered
                                  ▼
             234's host /hooks/events · ChatGPT · any client that subscribed
```

- **A webhook carries no authority.** It names a reference; the quote it belongs to (every reference holds the quote id) is checked again with the provider's own API, only while it is approved and waiting. A forged or repeated webhook costs one such check. Paystack's must carry `x-paystack-signature` (HMAC-SHA512 of the body); VTpass's is unsigned and is answered `{"response": "success"}`, as VTpass asks. The simulated checkout announces a payment by the same signed `charge.success`, so the simulated path is the real one.
- **The minute** (Cron Trigger) checks every quote approved more than 30 seconds ago again, expires every open quote past its time (a quote also expires when anyone reads it), and hands on due events. A lost webhook, an unread quote and a crashed delivery all end up here.
- **234's own host is a subscriber like any other.** When a quote's card is recorded it subscribes to that quote's `quote.finished`, as the chat's owner, with `PUBLIC_BASE_URL/hooks/events` and a key derived from `EVENTS_SECRET`. An event refreshes the card and is put to the model as an `event` input, which it answers at once; one delivered again (the same event id) adds nothing. An event for a chat that is gone answers 410, which ends the subscription. Without `EVENTS_SECRET` the host subscribes to nothing and cards update by polling.
- **Queues**: `PROVIDER_JOBS` and `EVENT_JOBS`, each retried five times and then dead-lettered. Where no queue is bound, the work runs at once; the unit tests hold it until a test runs it, as a Queue would.

## Events

The four money connectors offer [MCP events](https://developers.openai.com/plugins/build/mcp-events): a client can ask to hear when a quote ends instead of asking again. Memory offers none.

| Part | What it does |
|---|---|
| `events/list` | One event, `quote.finished`. It can follow one quote (`quote_id`) or every quote of the account on that connector. The payload holds `quote_id`, `connector`, `state` (settled, failed, abandoned, declined, unavailable, refund_due or expired), `amount_kobo` and `description`. |
| `events/subscribe` | Webhook delivery only. The secret is `whsec_` plus 24 to 64 bytes in base64. The callback is HTTPS on a host name, never an address or localhost, and no redirect is followed. It must echo a signed challenge before the subscription is kept. A subscription lasts 7 days by default and at most 30. Subscribing again with the same event, arguments and URL refreshes it. |
| `events/unsubscribe` | Ends the subscription of the account that asks, and only that one |
| The outbox | A trigger on the quotes table writes one row for each matching subscription when a quote ends, in the statement that ends it (`checkout/migrations/0006_events.sql`). No path that ends a quote can miss it. |
| Delivery | One event per request, signed with Standard Webhooks (`webhook-id`, `webhook-timestamp`, `webhook-signature`) and `X-MCP-Subscription-Id`. It is sent after the request that ended the quote, then retried every minute (Cron Trigger) with backoff from 30 seconds to an hour, up to 8 attempts, with the same event id. 2xx is delivered. 410 ends the subscription and 413 drops the event. Each row is claimed with a one-minute lease, so two senders never send it twice at once. |

**Not done:** replay (`cursor` is always null and events are not replayable), and dual signatures while a secret rotates. A refresh replaces the secret at once. The secret is kept in D1, because it is needed to sign.

## 234 MCP Ready

`ready/` checks any MCP server, and any plugin folder, against the rules a 234 host relies on.

```bash
node ready/cli.mjs https://example.com/mcp
```

```bash
node ready/plugin-cli.mjs plugins/234 --servers
```

| Rule | Level |
|---|---|
| The server names itself and gives the model instructions | must / should |
| Every tool has a real description, an object input schema and `readOnlyHint`. Every write tool has `destructiveHint` and `idempotentHint`. At most 25 tools are offered to the model. | must / should |
| A model-callable tool that takes an amount takes an idempotency key | must |
| The model cannot approve a payment: an approval tool is app-only or asks for the person's approval token | must |
| An unknown tool and a call without its required arguments are refused | must |
| Without credentials the server answers `401` with a Bearer challenge and protected resource metadata that names an authorization server and its scopes | must / should |
| With `--fixture`, the same call with the same idempotency key gives the same result | must |
| A plugin's `plugin.json` and `mcp.json` pass the official schemas (copied in `ready/plugin/schemas/`), every URL is HTTPS or `localhost`, no header or variable carries a credential, and a stdio command is one executable | must |
| Each skill's front matter names its directory and has a description of 1 to 1024 characters, and no package path leads outside the plugin | must |

`tools/check.sh` runs the checker against all five connectors, against the OAuth gateway with a token, and against `plugins/234`. The connectors themselves answer without sign-in (the host stands in front of them), so the direct checks show one warning for `auth.challenge`. The gateway passes it.
