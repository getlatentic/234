# 234 MCP Ready

Checks a remote MCP server (Streamable HTTP) against the rules a 234 host relies on, with the official TypeScript client.

```
node ready/cli.mjs <mcp-url> [--header "Authorization: Bearer ..."] [--fixture calls.json] [--json]
```

Exit code 1 when a **must** rule fails; **should** rules are warnings.

| Rule | Level |
|---|---|
| Handshake names the server; instructions tell the model how to use it | must / should |
| Tools: unique snake_case names, real descriptions, object input schemas, `readOnlyHint` on every tool, `destructiveHint` and `idempotentHint` on every write tool, at most 25 tools offered to the model | must / should |
| Money: every model-callable write tool that takes an amount takes an idempotency key; a tool the model can call may not approve a payment unless it demands the person's approval token (otherwise it is app-only) | must |
| Errors: an unknown tool and a call without required arguments are refused | must |
| Sign-in: without credentials the server answers 401 with a Bearer challenge and protected-resource metadata that names an authorization server and scopes | must / should |
| Replay (with `--fixture`): the same call with the same idempotency key gives the same result | must |

A fixture is `{ "calls": [{ "tool": "...", "args": { ... } }] }`. `ready.test.mjs` runs each rule against a server built to break it.
