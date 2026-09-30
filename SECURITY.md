# Security policy

## Reporting a vulnerability

Please report it privately, not in a public issue or pull request. Use GitHub's "Report a vulnerability" button on the
repository's Security tab, with what you found, the steps to reproduce it and, if you can, the commit you tested. You will get an answer within a few days. Please
give us a reasonable time to fix the problem before you publish it, and do not use it against the public demo
beyond what you need to show it.

## What is in scope

The project moves simulated money today, but it is built as if it moved real money. These matter most:

- **Approval bypass.** Anything that lets a payment be approved without the person pressing Approve on the card: the
  model, a prompt injection in a message or a tool result, another tab, a replayed or forged approval token, a card
  that approves for a different amount than it shows, or a second approval of one quote.
- **Owner isolation.** Reading or acting on another visitor's or account's chats, quotes, limits, receipts or approval
  tokens, including through share links, sign-in adoption, the A2A endpoints, the connectors' owner header or the
  sandbox.
- **Injection.** Script, HTML or link injection into the chat page or a card (Markdown in replies, card fields,
  `_meta`), a card reaching beyond its sandbox or declared origins, and prompt injection that changes an amount, a
  recipient, a bank or a product.
- **Limits and spend.** Getting past the per-payment, daily, per-visitor or model-call limits, or the once-only
  guarantees of the ledger, by races, retries or crafted inputs.
- **Secrets and sign-in.** A way to read a secret, forge a session, a Firebase token or a webhook signature, or to
  turn on a simulated provider's live mode.

## Out of scope

- Anything that needs a real provider account or real money: none is connected.
- Findings about the demo's simulated data, or that a visitor can clear cookies and get a new allowance (documented
  in [docs/deploy.md](docs/deploy.md)).
- Volume attacks, social engineering of maintainers, and reports from automated scanners without a demonstrated
  impact.
- Vulnerabilities in a dependency that do not affect this project: report those upstream.

## Supported versions

Only the latest commit on the default branch.

## Secrets

If you find a credential in this repository or its history, report it the same way. No credential is meant to be
there; the values that look like keys are fixtures and dummy tokens for tests ([.gitleaks.toml](.gitleaks.toml)).
