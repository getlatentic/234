# The 234 wallet, on Bachs' rails

**Design; build steps 1 to 4 are built, simulated (see Build order).** A treasury: Bachs takes payments for 234 into **234's own Bachs account**, and
234 keeps a wallet for each signed-in person in its own ledger, saying who owns what of that money. A person adds
money through a Bachs checkout (bank transfer or card), spends it on what 234 already does (airtime, data, food,
payments, transfers), and withdraws it to their own bank account.

```
top-up checkout (Bachs, into 234's account) ──► signed webhook ──► 234 journal: fund
234 quote, approved on a card ──► 234 journal: spend ──► VTpass / Paystack / the merchant, paid from 234's balances
journal: withdraw ──► Paystack transfer to the person's own account (name checked) ──► settled, or paid back
```

## The ledger is a journal, and the balance is its sum

`wallet_entry` is append-only: `fund`, `spend`, `release`, `refund`, `withdraw`, `withdraw_back`, `adjust`, each with
an owner, an amount in kobo, a `ref`, and `UNIQUE (owner, kind, ref)` so a webhook delivered twice, a retry, or a
resumed turn credits or debits once. **There is no balance column to drift:** the balance is the sum of the entries.

D1 has no interactive transactions, so no rule reads then writes (checkout/ledger/). A debit is one INSERT whose
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

No account per person and no BVN: every top-up is one Bachs checkout for an amount, made by 234 with the top-up's id
as its reference and a digest of the owner in its metadata, paid into 234's Bachs account (signed-in accounts
only: a visitor has no wallet). The webhook `collection.succeeded`, verified by its HMAC-SHA256 signature over `{timestamp}.{raw_body}`
(`X-Bachs-Signature-V2`), becomes a `fund` entry with `ref = the top-up id`; a webhook for a checkout 234 did not
make, or for another amount, credits nothing and is logged. **234 bears Bachs' fee** (1%, at most NGN 300): the wallet
is credited the full amount the person paid.


A Bachs webhook whose timestamp is more than five minutes old is refused (a replay), and Bachs is answered 2xx only
after the `fund` entry exists, so a lost write is delivered again. A top-up whose webhook never arrives is checked
with Bachs by the minute cron, as Paystack payments are now (`provider_hooks/rechecks.py`), if Bachs offers a lookup
by checkout: to confirm with Bachs.
## Withdrawing

Bachs pays out only to 234's own bank account, so a withdrawal is a transfer from 234's Paystack balance, through the
send-money machinery that exists: the account is resolved, and its name must match the person's account name. A
`withdraw` entry (guarded debit) goes first, then the transfer with the entry id as its idempotency key; success
settles it, failure writes `withdraw_back`. A card with the one-time token approves it.


A withdrawal has three outcomes, not two. A transfer that timed out or answers `pending` is undecided: it stays open
until a Paystack event or the minute re-check settles it, and it is never sent again under a new idempotency key
while it is undecided. `transfer.success` settles it; `transfer.failed` and `transfer.reversed` (a transfer that
succeeded and came back) write `withdraw_back`.
## Where the money is, and the float

The sum of all wallets is what 234 owes. The money arrives in 234's Bachs balance; 234 pays VTpass and Paystack from
their own balances, and **234 tops those up** from its Bachs settlements. The ledger does not move that money; it tracks the debt, so the
code ships a **reconciliation** (`/ops/wallet/reconcile`): total owed, against Bachs' balance plus the providers',
alert on a gap, and freeze funding on a mismatch. Who tops up the providers, and how often, is operations.

## Safety limits

Wallet balance cap (`WALLET_BALANCE_CAP_KOBO`, default NGN 200,000), per-withdrawal and daily withdrawal caps
(`WALLET_WITHDRAWAL_KOBO`, NGN 50,000; `WALLET_WITHDRAWALS_DAILY_KOBO`, NGN 100,000), all set by 234, a freeze flag per wallet, and every existing limit of
the ledger on every spend. A PACT agent's own chats (`p:` owners) have no wallet. A person's agent that holds the
`payments` scope spends from the wallet only through the same card.

## Modes

`BACHS_MODE=simulated|sandbox|live`, as the Paystack modes are. Simulated is a Bachs stand-in in the connectors
Worker (a pay-in page like the Paystack simulator's, signed webhooks). Sandbox uses `sandbox-api.bachs.io` with the
sandbox key (`BACHS_SECRET_KEY`, which must start `sk_sandbox_`) and the webhook endpoint's signing secret
(`BACHS_WEBHOOK_SECRET`). Live refuses to start, and a live key is refused in any mode.

## Build order

1. **Built.** The journal, the guarded debit and credit, the invariants, and tests that race spends (no Bachs):
   `checkout/migrations/0011_wallet.sql`, `checkout/src/checkout/wallet/journal.py` and `settings.py`
   (the caps), tests `checkout/tests/test_wallet_{journal,races,settings}.py`.
2. **Built.** Spend from the wallet in the airtime flow (hold, claim, release, refund), simulated:
   `checkout/src/checkout/wallet/spending.py`, `flows/wallet_leg.py`, and `AirtimeFlow.approve(..., funding="wallet")`.
   The wallet's claim is the quote's own `open → approved` UPDATE (`Ledger.claim_approval` with `ClaimTerms`),
   which marks the quote `funding = wallet` and requires a hold of its amount with no release; a release is
   written only while no quote of that id is marked as paid from the wallet, so the two exclude each other in
   SQL. A wallet-paid quote starts no Paystack checkout. A refund ends the quote as `failed` with the money back
   in the wallet. Tests `checkout/tests/test_wallet_spending.py`; guards `checkout/tools/mutations/wallet_rules.py`.
   A hold orphaned by a crash between hold and claim waits for the reaper of step 6.
3. **Built, simulated; the sandbox adapter is written but not yet exercised against Bachs.** The top-up and its
   webhook: `checkout/migrations/0012_wallet_topup.sql` (`wallet_topup`, open → paid | expired) and
   `0013_bachs_simulator.sql`; `checkout/src/checkout/wallet/topups.py` (start: one guarded INSERT requiring the
   owner's unfrozen wallet and the balance plus the amount within the cap, then the Bachs checkout with the top-up
   id as reference and Idempotency-Key, the owner only as a digest in its metadata; a checkout Bachs could not make
   leaves the top-up expired; the minute cron expires the rest) and `topup_credit.py` (the collection must name
   234's checkout, owner digest, `SUCCEEDED`, NGN and exactly the amount, or it credits nothing and is audited;
   then `fund` with `ref = top-up id`, and one UPDATE marks it paid only while that entry exists).
   `checkout/src/checkout/bachs/` holds the client (`POST /v1/checkout-sessions`, sandbox keys only), the
   signature check (any `v1`, at most five minutes old, at most 30 s ahead), the event reader, `BACHS_MODE`, and
   the simulator. `POST /hooks/bachs` (`provider_hooks/bachs.py`) answers 400 to an unverified delivery, 2xx only
   once the `fund` entry exists or the delivery can never credit, and 503 when the cap refuses the credit today, so
   Bachs delivers it again. The stand-in's pay page (`/sim/bachs/<checkout>`, `sim_bachs.py`) sends a signed
   `collection.succeeded` through the same hook. A genuine collection for an expired top-up is still credited.
   Tests `checkout/tests/test_bachs_*.py`, `test_wallet_topup*.py`; guards `checkout/tools/mutations/topup_rules.py`.
   Not yet: a credit the cap refuses for good
   (past Bachs' retries) waits for reconciliation in step 6; the re-check of a top-up whose webhook never arrives
   waits on whether Bachs offers a lookup by checkout.
4. **Built, simulated.** The `wallet` connector and its card, and paying airtime from the wallet on the
   approval card. `checkout/src/checkout/connectors/wallet.py`: one model tool, `wallet_balance` (read-only:
   the balance as a line, and the card), and two the card calls, `wallet_view` and `start_topup` (whole naira,
   ₦100 to ₦1,000,000; the cap and the freeze are the top-up's own). Every call acts for the signed-in account
   (`wallet/access.py`): the memory owner header, which the host sends only for an account's calls, naming
   the same key as the ledger owner; the Worker refuses a wallet call without it (`http.py`), and the wallet
   row is opened the first time that account asks, never for a visitor. `wallet/view.py` says the latest
   entries in plain words (Added, Paid airtime, Returned). `approve_quote` takes an optional `funding`
   (`checkout`, the default and the checkout as before, or `wallet`); it is an app-only tool, so only a card
   passes it, and `wallet` needs the account. The approval card is offered "Pay from wallet", without the
   balance, which a shared chat's guest would read (`flows/wallet_leg.py`, `wallet_offer`) only for an account whose balance covers an open quote; a refusal
   (`WALLET_SHORT`, `WALLET_FROZEN`) shows on the card as one line. The card is `card/wallet/` (balance, the
   last five entries, Add money opening the Bachs checkout, then reading the wallet until the money shows).
   The host (`host/src/turns/wallet.py`, `permissions.py`, `card_calls.py`, `hub.py`) shows and relays the
   wallet to an account's turns and cards alone, tells every connector when a call is an account's, refuses a
   guest of a shared chat any wallet call and any approval paid from the wallet (`chat/views/cards.py`), and
   offers no wallet to an outside OAuth client (`oauth/resources.py`). The system prompt names no wallet: the
   tool's description is the model's guide. Tests `checkout/tests/test_wallet_{connector,approval_card}.py`,
   `host/tests/test_wallet.py`, `conformance/card-states.mjs` (the offer on the card) and
   `conformance/chat-wallet.mjs` (signed in: add money on the simulated Bachs page, pay airtime from the
   wallet, the balance goes down); guards `checkout/tools/mutations/wallet_card_rules.py`. Withdrawing is
   step 5. A guest of a shared chat sees "Pay from wallet" on an approval card the owner made, never the
   balance, and any wallet call of theirs is refused.
5. Withdrawal through Paystack. 6. Reconciliation, the reaper, metrics. 7. Evaluation with the real model for wallet turns.

## Decided (2026-10-10)

Treasury model: payments into 234's Bachs account, balances in 234's ledger. 234 bears Bachs' collection fee, sets
the caps, and tops up Paystack and VTpass. No BVN for a wallet.

## Still open before real money

- **The licence for holding people's balances.** Bachs' public pages state none for itself and list wallets and money
  transmission among unsupported businesses: ask Bachs in writing whether this use is accepted, and which licence
  covers 234 holding balances for people.

## Not copied from elsewhere

From a public "build a digital wallet" series (2021): card numbers never pass through 234 (Paystack's own page takes
them); a payment is credited from a verified webhook or a re-check, never from the charge's first answer; the amount
credited is the provider's, never one the caller sends; no provider call happens inside an open database transaction.
