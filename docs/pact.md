# 234 and personal agents (PACT)

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
| An agent names its Users, and each is an owner with an allowance of their own, so the chats it holds as itself also carry its payer group: what all its Users approve in a day is capped together (`GROUP_DAILY_LIMIT_KOBO`, ₦500,000). A delegated chat is the person's account and pays within the account's own limit. | `pact/identity.py`, `turns/hub.py`, `checkout/src/checkout/ledger.py` |
| The database keeps SHA-256 digests of device codes and refresh tokens, never the values | `models.py` |

Tests:

- **Unit tests:** `host/tests/test_pact.py`, `test_pact_delegation.py`, `test_permissions.py`, `test_es256.py` (including RFC 7515's ES256 example), `test_jwks.py` and `test_scope.py`. Tokens and receipts are verified with `cryptography`, not with the host's own code. The tests run with SQLite raising D1's exception type for a broken constraint.
- **Identity, end to end:** `conformance/pact-e2e.mjs` runs PACT's own conformance suite, pinned to a commit, against a local stack started with `PACT=1`, and the Identity profile passes in full.
- **Delegated, end to end:** the suite's own Delegated test is written for its reference Brand. So `conformance/pact-delegated.mjs` takes its steps with the suite's own client library (`DeviceCodeClient`, `DelegatedA2AClient`, `verifyReceipt`) on a stack with `AUTH=1 PACT=1`, and a real browser signs in through the Firebase Auth emulator and unticks a scope. It captures the consent page as `docs/screens/pact-consent-{light,dark}.png`.
- **Mutation rules:** `checkout/tools/mutations/pact_rules.py` undoes each rule above and checks that a test fails.

**Seeing and ending them.** A signed-in person opens Connected apps in the chats drawer. It lists every personal agent they allowed: its host, the Brand, what it can do, and the date. It also lists every MCP client, such as Claude or ChatGPT, with the connectors it opens. Disconnect ends either at once. An agent's delegation token is refused from its next message, and its refresh token from its next refresh. A client's tokens are deleted (`accounts/connected.py`, `tests/test_connected.py`, `checkout/tools/mutations/connected_rules.py`). A grant also ends after 30 days, or when its refresh token is used twice. `conformance/pact-delegated.mjs` disconnects an agent in the browser and captures the sheet as `docs/screens/connected-apps-{light,dark}.png`.

The specification's text calls the security scheme `paJwt`, and the suite and the reference Provider use `platformJwt`, so the card names both for the same JWT. Reported as [openpactprotocol/openpactprotocol#42](https://github.com/openpactprotocol/openpactprotocol/issues/42).

## 234 as a person's agent at other Brands

234 also plays the other part: it is a personal agent itself, and talks to other Brands' own assistants for the person. The owner chooses which Brands it can reach (`PACT_REACH`), as the marketplace is the owner's. People see them; they don't add them. The model gets a connector of 234's own, `brands`, which the host serves itself (`host/src/turns/reach/`):

- `list_brands` shows each Brand's name, what it does (from its Agent Card), and what the person has let 234 do there.
- `message_brand` sends one request, in the person's words, and returns the Brand's reply. Each person keeps one conversation per Brand.

**Who 234 is to a Brand.** Every message carries a JWT that 234 signs with its own P-256 key (`PACT_AGENT_KEY`). The issuer is 234's address, and the public key is at `/.well-known/jwks.json`. The `sub` is a digest of the Brand's card and the person's ledger key. It is stable for that person, different at every Brand, and tells the Brand nothing about who they are. 234 registers with a Provider once: PACT's reference Provider takes a JWT signed by the same key at `POST /api/platforms`. That Provider registers ES256 agents only, which is why the key is P-256 while the host's own Delegated key is RSA.

**When a Brand needs the person's permission.** The Brand answers `TASK_STATE_AUTH_REQUIRED` with the scopes it needs. Only a person signed in to 234 can give it, so that they can always see and end it in Connected apps. A visitor still talks to the Brand, and when it needs permission the model asks them to sign in first, with no card and no sign-in started at the Brand. For an account, 234 starts the device flow for them, and the model shows a card: a title naming the Brand, and a button that opens the Brand's own sign-in page. The Brand shows what it asks for on its own consent page, where the person can untick any of it. 234 never sees the person's password, and the card never sees a token. The card asks how the sign-in stands, at the Brand's interval. When the Brand issues the token, the card says "I've signed in with …" in the chat, once, and the model sends the request again. 234 keeps the token for that person and that Brand, refreshes it before it runs out, and drops it when the Brand refuses it.

**Receipts.** 234 checks every receipt as PACT's own client does. The Brand's key, from the JWKS its metadata names, must have signed it. The signed payload must equal the claims shown, and the receipt must name 234 and that Brand. Only then is it kept, and the person is told it checked out. A receipt that fails is not kept, and the person is told why.

**Ending it.** Connected apps lists the Brands where 234 acts for the person. Disconnect asks the Brand to revoke the grant when the Brand's authorization server metadata names a `revocation_endpoint` (RFC 7009): the refresh token first, then the access token, each with 234's signed JWT as on its other OAuth calls. 234 then forgets its tokens and the conversation there. PACT itself defines no revocation for agents, and its reference Provider offers none, so for such a Brand the person is told to end it in that Brand's own settings. The Brand's token still lives at most an hour and works only with 234's own signed JWT, so once 234 has forgotten it, nobody can use it.

| Rule | Where |
|---|---|
| A person's `sub` names both the Brand and the person, and nothing that identifies them | `turns/reach/agent.py` |
| A conversation, a delegation and a sign-in card belong to one person: every statement names their ledger key | `turns/reach/store.py` |
| The Brand's token endpoint is asked no faster than its interval. Two cards polling at once settle a sign-in once, and only the one that settled it tells the chat. | `turns/reach/signing_in.py`, `store.settle` |
| A delegation token the Brand refuses is dropped, and the request is sent again without it | `turns/reach/server.py` |
| Only a signed-in account starts a sign-in at a Brand: the hub tells the host's own connectors in the call's `_meta` | `turns/hub.py`, `turns/reach/server.py` |
| Disconnect revokes at the Brand where it can, and counts it ended only when the Brand answers 200 to both tokens | `turns/reach/signing_in.py`, `accounts/connected.py` |
| A receipt is kept only when it holds | `turns/reach/receipts.py` |
| ES256 signatures use RFC 6979 nonces (the RFC's own test vector passes), a Montgomery ladder, and a check against the public key before they leave | `host/src/signatures/ec_key.py` |
| `brands` is offered only to the host's own chats. It is not on the OAuth gateway, and not in a PACT Brand's chat, so an agent calling 234 never makes 234 call other Brands. | `turns/settings.py`, `turns/scope.py` |

Tests:

- **Unit tests:** `host/tests/test_reach.py` runs the connector against a fake Brand's Provider (`tests/reach_support.py`), with receipts signed ES256 as the reference Provider signs them. `test_signatures.py` covers the ES256 key, including RFC 6979's test vector and a check with `cryptography`.
- **End to end:** `conformance/pact-reach.mjs` (a stack with `AUTH=1 REACH=1`) starts PACT's own reference Provider, its database and its Skyline Brand app from the pinned suite, and registers 234 there. A visitor in 234's chat asks Skyline about a flight (Identity), then about their upcoming flights, and is asked to sign in to 234. Signed in, they sign in at Skyline's own login page and allow one scope. 234 asks again, gets the answer with a receipt it checks, and rebooking then steps up for the scope left out. They disconnect Skyline in Connected apps, are told to end it in Skyline's settings, and the next request asks for permission again. Screenshots: `docs/screens/reach-sign-in-card-{light,dark}.png`.
- **Mutation rules:** `checkout/tools/mutations/reach_rules.py`.

**Not done:** Brands no Provider has registered 234 at cannot be reached: registration is per Provider, by the owner.
