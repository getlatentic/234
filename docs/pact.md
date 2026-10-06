# 234 for personal agents (PACT)

A person's own agent (on their phone, in their assistant) can talk to 234 for them over [PACT 1.0](https://openpactprotocol.org/spec), the Personal Agent Consent and Trust Protocol, on A2A 1.0's HTTP+JSON binding. 234 is the Provider and implements the Identity profile: the agent signs a short JWT that names the person, and 234 answers as itself, in a conversation of its own for that person. Every payment still waits for the person on a card.

## What an agent goes through

1. It reads the Brand's Agent Card at `/a2a/<brand>/.well-known/agent-card.json`, with no token. It names the interface `/a2a/<brand>` and one security scheme, a Bearer JWT.
2. It signs a JWT with its own key: `iss` is its registered issuer, `aud` is the audience 234 gave it, `sub` names the person, and the token lives at most 300 seconds.
3. It posts `/a2a/<brand>/message:send` with a text message. 234 answers synchronously with one `{message}` and a `contextId`. The next message with that `contextId` continues the conversation.
4. When 234 has prepared a payment, the reply says so and links to the chat. The person opens it and approves on the card. 234 doesn't ask the agent to approve.

`GET tasks` lists nothing, and the task, stream, extended card and push routes answer with the errors the spec names. 234 never makes a task.

## Configuration

| Variable | What it holds |
|---|---|
| `PACT_AGENTS` | The agents 234 accepts, as JSON: `[{"issuer", "jwks_uri", "enabled"}]`. A `jwks_uri` is HTTPS (loopback HTTP only with `DJANGO_DEBUG`). Empty: no agent is accepted. |
| `PACT_AUDIENCE` | The one `aud` 234 accepts. Empty: every token is refused. |
| `PACT_BRANDS` | The Brands, as JSON: `{"<id>": {"name", "description", "connectors"}}`. Default: `234` with every connector. |

With neither agents nor an audience set, as in the public deployment, the cards are readable and every call is `401`.

## The rules the server enforces

| Rule | Where |
|---|---|
| A token is ES256 or RS256, signed by a key in a registered, enabled agent's JWKS, for this host's audience, with a `sub`, issued at most 30 s ahead and living at most 300 s. Any other is `401` with `WWW-Authenticate: Bearer realm="a2a"`, and the reason is logged, not sent. | `host/src/pact/identity.py`, `es256.py` |
| An agent's keys are kept as its `Cache-Control` says (one minute to a day). An unknown key id refetches them at most once every ten seconds, so a rotated key works within seconds and random key ids can't flood the agent. No redirect is followed. | `jwks.py`, `transport.py` |
| Each person of an agent is an owner of their own: the owner is a digest of (`iss`, `sub`), so two agents' users never share a ledger, a limit or a chat. | `identity.Caller` |
| A `contextId` continues only for the person and Brand that started it. Any other is `Unknown contextId`. | `conversation._context` |
| A repeated `messageId` gets the stored reply and runs nothing. One `INSERT … ON CONFLICT DO NOTHING RETURNING` decides it, because D1 raises its own exception type for a broken constraint. | `conversation._claim` |
| A Brand's chat shows the model only the Brand's connectors, and a call to any other connector's tool is refused | `host/src/turns/scope.py`, `runner.py` |
| Only text parts (`text`, with `mediaType` `text/plain` if any) are read. Anything else is `CONTENT_TYPE_NOT_SUPPORTED`. | `conversation.read` |
| An unmatched route or method is `404` or `405` with no body, before authentication | `views.route` |
| Messages are rate limited per person | `views._send` |

Tests: `host/tests/test_pact.py`, `test_es256.py` (including RFC 7515's ES256 example), `test_jwks.py` and `test_scope.py`. They run with SQLite raising D1's exception type for a broken constraint. `conformance/pact-e2e.mjs` runs PACT's own conformance suite, pinned to a commit, against a local stack started with `PACT=1`. Its Identity profile passes in full. `checkout/tools/mutations/pact_rules.py` undoes each rule above and checks that a test fails.

**Not done:** PACT's Delegated profile (device authorization, delegation tokens 234 signs, read and write scopes, signed receipts and step-up). The specification's text calls the security scheme `paJwt` and the suite looks for `platformJwt`, so the card names both, for the same JWT.
