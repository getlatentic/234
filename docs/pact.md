# 234 for personal agents (PACT)

A person's own agent (on their phone, in their assistant) can talk to 234 for them over [PACT 1.0](https://openpactprotocol.org/spec), the Personal Agent Consent and Trust Protocol, on A2A 1.0's HTTP+JSON binding. 234 is the Provider and implements both profiles:

- **Identity.** The agent signs a short JWT that names the person, and 234 answers in a conversation of its own for that person.
- **Delegated.** The person signs in to 234 and allows the agent to act as their 234 account, within scopes they choose.

Every payment still waits for the person on a card.

## Identity: what an agent goes through

1. It reads the Brand's Agent Card at `/a2a/<brand>/.well-known/agent-card.json`, with no token. The card names the interface `/a2a/<brand>` and the Bearer JWT.
2. It signs a JWT with its own key: `iss` is its registered issuer, `aud` is the audience 234 gave it, `sub` names the person, and the token lives at most 300 seconds.
3. It posts `/a2a/<brand>/message:send` with a text message. 234 answers synchronously with one `{message}` and a `contextId`. The next message with that `contextId` continues the conversation.
4. When 234 has prepared a payment, the reply says so and links to the chat. The person opens it and approves on the card. 234 doesn't ask the agent to approve.

`GET tasks` lists nothing, and the task, stream, extended card and push routes answer with the errors the spec names. The only task 234 returns is a step-up (below), and it isn't stored.

## Delegated: acting as the person's account

Where people can sign in to 234 and the host has a signing key, each Brand's card adds a device-code scheme with the Brand's scopes:

| Scope | What the person allows |
|---|---|
| `memory:read` | See what you asked 234 to remember: saved recipients, preferences and facts. |
| `memory:write` | Offer to remember, change or forget something for you. You press Save on each one. |
| `payments` | Prepare payments, purchases and transfers from your 234 account, and check how they stand. You approve every payment on a card. |

A Brand offers the scopes of its connectors: `memory:*` with the memory connector, `payments` with any other.

1. **The agent asks.** It posts `/a2a/<brand>/oauth/device_authorization` (RFC 8628) with its JWT, `client_id` set to its issuer, and the scopes. It gets a device code, a user code such as `BCDF-GHJK`, and a link.
2. **The person decides.** The link opens `/a2a/<brand>/oauth/device` on 234. The person signs in with Google first. Then the page names the agent's host and the Brand, shows the code to check against the agent, and lists each scope as a ticked checkbox with the words above. The person can untick any of them, then presses Allow or Don't allow.
3. **The agent gets a token.** It polls `/a2a/<brand>/oauth/token` and gets `authorization_pending`, `slow_down`, `access_denied` or `expired_token` until the person has decided. Then it gets a delegation token, valid for an hour at most, and a refresh token. `scope` lists only what the person left ticked.
4. **It sends with the token.** The agent sends the token in `X-A2A-User-Delegation` next to its own JWT. The turn runs as the person's account, in a chat of that account, so the person also sees it in their 234 chat list. The model may use only what the scopes allow there.
5. **The reply carries a receipt.** `metadata["pact.receipt"]` holds a JWS of claims: the grant, the account, the agent, the Brand, the scopes the turn's tool calls used, and each tool that ran with a SHA-256 of its arguments. The host signs it with the key in `/a2a/<brand>/oauth/jwks.json`, which the RFC 8414 metadata names.

**Step-up.** A request that needs a scope the message lacks isn't failed. Examples: "recall Mum" with no token, or "remember that I live in Yaba" without `memory:write`. The tool call is refused, and the model says in a sentence what it needs. The reply is a task in `TASK_STATE_AUTH_REQUIRED` with `metadata["pact.missingScopes"]`. The agent asks for those scopes as in step 1 and sends again with the same `contextId`.

**A conversation that moves to the account.** A context begun with no token moves to a new chat of the account on its first delegated message. The `contextId` stays the same. The first chat keeps its owner, so an approval link handed out for it never opens the account's chat. From then on the context needs a token for that account. With no token it's `INVALID_PARAMS`, and with another account's token it's `INVALID_PARAMS` too.

## Configuration

| Variable | What it holds |
|---|---|
| `PACT_AGENTS` | The agents 234 accepts, as JSON: `[{"issuer", "jwks_uri", "enabled"}]`. A `jwks_uri` is HTTPS (loopback HTTP only with `DJANGO_DEBUG`). Empty: no agent is accepted. |
| `PACT_AUDIENCE` | The one `aud` 234 accepts and tells each agent it registers. Default: the host's A2A address, `https://234.getlatentic.com/a2a` in the public deployment, as PACT's reference Provider does. |
| `PACT_BRANDS` | The Brands, as JSON: `{"<id>": {"name", "description", "connectors"}}`. Default: `234` with every connector. |
| `PACT_SIGNING_KEY` (secret) | The RSA private JWK that signs delegation tokens and receipts. `tools/pact-key.mjs` makes one; `tools/deploy.sh` makes it once and `rotate PACT_SIGNING_KEY` replaces it, after which tokens and receipts signed with the old key stop verifying. |

Agents are registered by the owner only: there is no self-registration endpoint like the reference Provider's `POST /api/platforms`, so a JWKS URL is never one a stranger chose. With no agents listed, as in the public deployment, the cards are readable and every call is `401`.

## The rules the server enforces

| Rule | Where |
|---|---|
| A personal-agent token is ES256 or RS256, signed by a key in a registered, enabled agent's JWKS, for this host's audience, with a `sub`, issued at most 30 s ahead and living at most 300 s. Any other is `401` with `WWW-Authenticate: Bearer realm="a2a"`, and the reason is logged, not sent. | `host/src/pact/identity.py`, `es256.py` |
| An agent's keys are kept as its `Cache-Control` says (one minute to a day). An unknown key id refetches them at most once every ten seconds, so a rotated key works within seconds and random key ids can't flood the agent. No redirect is followed. | `jwks.py`, `transport.py` |
| Each person of an agent is an owner of their own: the owner is a digest of (`iss`, `sub`). Two agents' users never share a ledger, a limit or a chat. | `identity.Caller` |
| A `contextId` continues only for the person and Brand that started it. Any other is `Unknown contextId`. | `conversation._context` |
| A repeated `messageId` gets the stored reply, message or task, and runs nothing. One `INSERT … ON CONFLICT DO NOTHING RETURNING` decides it, because D1 raises its own exception type for a broken constraint. | `conversation._claim` |
| A Brand's chat shows the model only the Brand's connectors, and a call to any other connector's tool is refused | `host/src/turns/scope.py`, `permissions.py` |
| Only text parts (`text`, with `mediaType` `text/plain` if any) are read. Anything else is `CONTENT_TYPE_NOT_SUPPORTED`. | `conversation.read` |
| An unmatched route or method is `404` or `405` with no body, before authentication | `views.route` |
| Messages and device authorizations are rate limited per person, and consent decisions per account | `views._send`, `oauth_views.py` |
| Every OAuth call carries the agent's JWT, and its `client_id` must be the JWT's issuer (otherwise `401 invalid_client`) | `oauth_views.from_agent` |
| A device code answers only the person of the agent that asked for it, at the Brand it was asked at. It is taken once, for the scopes the person left ticked. Unticking everything is a refusal. | `device.py` |
| A refresh token works once, for the same person of the same agent. Used twice, it ends its grant. | `grants.py` |
| A delegation token is accepted only if this host signed it for this Brand's interface and issuer, it hasn't expired, its `client_id` is the agent sending it, and its grant is live and was made for this very person of that agent. Otherwise it's `401` with `error="invalid_token"` and no body. | `delegation.py`, `signing.py` |
| A turn's scopes are those on the message that drove it. With scopes, a call needing one the message lacks is refused and names it. The notes are read only with `memory:read`. An agent's own owner (`p:`) pays without a scope, since it isn't the person's account. | `turns/permissions.py`, `tool_calls.py` |
| The database keeps SHA-256 digests of device codes and refresh tokens, never the values | `models.py` |

Tests:

- **Unit tests:** `host/tests/test_pact.py`, `test_pact_delegation.py`, `test_permissions.py`, `test_es256.py` (including RFC 7515's ES256 example), `test_jwks.py` and `test_scope.py`. Tokens and receipts are verified with `cryptography`, not with the host's own code. The tests run with SQLite raising D1's exception type for a broken constraint.
- **Identity, end to end:** `conformance/pact-e2e.mjs` runs PACT's own conformance suite, pinned to a commit, against a local stack started with `PACT=1`, and the Identity profile passes in full.
- **Delegated, end to end:** the suite's own Delegated test is written for its reference Brand. So `conformance/pact-delegated.mjs` takes its steps with the suite's own client library (`DeviceCodeClient`, `DelegatedA2AClient`, `verifyReceipt`) on a stack with `AUTH=1 PACT=1`, and a real browser signs in through the Firebase Auth emulator and unticks a scope. It captures the consent page as `docs/screens/pact-consent-{light,dark}.png`.
- **Mutation rules:** `checkout/tools/mutations/pact_rules.py` undoes each rule above and checks that a test fails.

**Seeing and ending them.** A signed-in person opens Connected apps in the chats drawer. It lists every personal agent they allowed: its host, the Brand, what it can do, and the date. It also lists every MCP client, such as Claude or ChatGPT, with the connectors it opens. Disconnect ends either at once. An agent's delegation token is refused from its next message, and its refresh token from its next refresh. A client's tokens are deleted (`accounts/connected.py`, `tests/test_connected.py`, `checkout/tools/mutations/connected_rules.py`). A grant also ends after 30 days, or when its refresh token is used twice. `conformance/pact-delegated.mjs` disconnects an agent in the browser and captures the sheet as `docs/screens/connected-apps-{light,dark}.png`.

The specification's text calls the security scheme `paJwt`, and the suite and the reference Provider use `platformJwt`, so the card names both for the same JWT. Reported as [openpactprotocol/openpactprotocol#42](https://github.com/openpactprotocol/openpactprotocol/issues/42).
