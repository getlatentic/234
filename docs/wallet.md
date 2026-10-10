# The 234 wallet, on Bachs' rails

**Design. Nothing here is built yet.** 234 keeps its own wallet: a balance for each signed-in person, held in 234's
ledger. Bachs is not the wallet; it is the way money gets in and out. A person funds the wallet by sending naira to a
bank account number that Bachs gives them, spends it on the things 234 already does (airtime, data, food, payments,
transfers), and withdraws it to their own bank account.

```
bank transfer ──► Bachs virtual account ──► webhook ──► 234 journal: fund
   234 quote, approved on a card ──► 234 journal: spend ──► VTpass / Paystack / the merchant, paid from 234's float
journal: withdraw ──► Bachs payout to the person's own verified bank account ──► webhook ──► settled, or paid back
```

## The ledger is a journal, and the balance is its sum

`wallet_entry` is append-only: `fund`, `spend`, `release`, `refund`, `withdraw`, `withdraw_back`, `adjust`, each with
an owner, an amount in kobo, a `ref`, and `UNIQUE (owner, kind, ref)` so a webhook delivered twice, a retry, or a
resumed turn credits or debits once. **There is no balance column to drift:** the balance is the sum of the entries.

D1 has no interactive transactions, so no rule reads then writes (checkout/ledger.py). A debit is one INSERT whose
`WHERE` holds the rule: `(SELECT COALESCE(SUM(signed), 0) FROM wallet_entry WHERE owner = ?) >= amount AND the
wallet is not frozen`. The rows it inserted say whether the caller won. Two spends that cannot both fit cannot both land.

## Spending: hold, claim, release

A quote paid from the wallet (`funding = wallet`) is approved on the same card with the same one-time token. In order:

1. **Hold:** insert `spend` with `ref = quote id`, guarded by the balance. No funds, no hold, and the card says so.
2. **Claim:** the quote's existing single `open → approved` UPDATE, with its per-payment, daily and group limits.
3. **Release:** if the claim lost (already approved, over a limit, expired), insert `release` for the same ref.

A crash between 1 and 2 leaves a hold on a quote nobody approved; the minute cron releases holds whose quote is not
approved after its TTL. A provider that fails after approval (VTpass `refund_due`) pays back with `refund`, keyed by the
quote. The model never touches the wallet: its one tool, `wallet_balance`, reads, and every movement is a card.

## Funding

One Bachs Connect sub-account and one NGN virtual account per person, made when they first ask to add money
(signed-in accounts only: a visitor has no wallet). The webhook `collection.succeeded`, verified by its HMAC-SHA256
signature over `{timestamp}.{raw_body}` (`X-Bachs-Signature-V2`), becomes a `fund` entry with `ref = the event id`.
Bachs charges 1% (at most NGN 300) to collect: the wallet is credited what arrives net of it, and says so.

## Withdrawing

Only to a bank account Bachs has verified as the person's own. A `withdraw` entry (guarded debit) goes first, then the
Bachs payout with the entry id as its idempotency key; `payout.paid` settles it, `payout.failed` writes `withdraw_back`.
A card with the one-time token approves it, and it has its own daily cap.

## Where the money is, and the float

The sum of all wallets is what 234 owes. The money itself arrives in 234's Bachs balance and is paid out to VTpass and
Paystack from their balances, which someone tops up. The ledger does not move that money; it tracks the debt, so the
code ships a **reconciliation** (`/ops/wallet/reconcile`): total owed, against Bachs' balance plus the providers',
alert on a gap, and freeze funding on a mismatch. Who tops up the providers, and how often, is operations.

## Safety limits

Wallet balance cap, per-withdrawal and daily withdrawal caps, a freeze flag per wallet, and every existing limit of
the ledger on every spend. A PACT agent's own chats (`p:` owners) have no wallet. A person's agent that holds the
`payments` scope spends from the wallet only through the same card.

## Modes

`WALLET_MODE=simulated|sandbox|live`, as the Paystack modes are. Simulated is a Bachs stand-in in the connectors
Worker (a pay-in page like the Paystack simulator's, signed webhooks). Sandbox uses `sandbox-api.bachs.io` with the
sandbox key. Live refuses to start without an explicit flag and the answers below.

## Build order

1. The journal, the guarded debit and credit, the invariants, and tests that race spends (no Bachs).
2. Spend from the wallet in the airtime flow (hold, claim, release, refund), simulated.
3. The Bachs stand-in and webhook, then the sandbox adapter (virtual account, signature check).
4. The `wallet_balance` tool and the wallet card (balance, add money, withdraw).
5. Withdrawal. 6. Reconciliation, the reaper, metrics. 7. Evaluation with the real model for wallet turns.

## What the owner must answer before any real money

- **Custody and licence.** Who holds the money (234, Bachs, a bank) and under which CBN licence. Bachs' public docs
  state none, and list wallets and money transmission as unsupported businesses: ask Bachs in writing.
- **Who bears Bachs' 1% to collect,** the balance cap, and the withdrawal caps.
- **Who tops up the providers,** and the reconciliation tolerance.
- **KYC:** whether a wallet needs BVN for the person (Bachs' virtual accounts do).
