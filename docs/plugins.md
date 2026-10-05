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
| Everything is `404` while sign-in is off | `views.signing_in` |

Tests: `host/tests/test_oauth.py` (44 cases). `conformance/mcp-oauth.mjs` runs the whole flow with the official TypeScript MCP client and a real browser against the Firebase Auth emulator. Two accounts each approve a client, and one account cannot see the other's quote.

**Not done:** custom URI schemes for native apps (`cursor://…`) are refused, because the MCP authorization spec allows only HTTPS and loopback redirects. There is no page that lists the clients a person has allowed. A grant ends when the client revokes it or after 30 days without a refresh.

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
