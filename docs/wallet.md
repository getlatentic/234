# The 234 wallet, on Bachs' rails

**Design; build steps 1 to 6 are built, simulated, and step 7 is measured with the real model (see Build order).** A treasury: Bachs takes payments for 234 into **234's own Bachs account**, and
234 keeps a wallet for each signed-in person in its own ledger, saying who owns what of that money. A person adds
money through a Bachs checkout (bank transfer or card), spends it on what 234 already does (airtime, data, food,
payments, transfers), and withdraws it to their own bank account.

```
top-up checkout (Bachs, into 234's account) ──► signed webhook ──► 234 journal: fund
234 quote, approved on a card ──► 234 journal: spend ──► VTpass / Paystack / the merchant, paid from 234's balances
journal: withdraw ──► Paystack transfer to the person's own account (name checked) ──► settled, or paid back
```

## The ledger is a journal, and the balance is its sum

`wallet_entry` is append-only: `fund`, `spend`, `release`, `refund`, `withdraw`, `withdraw_back`, `dispute`,
`dispute_back`, `adjust`, each with
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

A crash between 1 and 2 leaves a hold on a quote nobody approved; the minute cron gives back a hold five minutes
old whose quote is not paid from the wallet, with the same guarded release, so a claim that lands later loses. A provider that fails after approval (VTpass `refund_due`) pays back with `refund`, keyed by the
quote, and so does one that reverses a delivered order (Reversals, below): a quote is refunded once, however it ended.
The model never touches the wallet: its one tool, `wallet_balance`, reads, and every movement is a card.

## Reversals

VTpass can take back airtime or data after reporting it delivered: the order bounced at the network, and VTpass
returns the money to 234's VTpass wallet. Its `transaction-update` callback then carries `code` 040 ("TRANSACTION
REVERSAL TO WALLET") and `content.transactions.status` `reversed`, as against `failed` for an order refused on
request (https://vtpass.com/documentation/transaction-update-webhook-api/; code 040 is "TRANSACTION REVERSAL" in
https://vtpass.com/documentation/response-codes/). The requery page shows only a delivered reply
(https://vtpass.com/documentation/re-query-services/), so 234 reads a requery as a reversal on the same two fields:
status `reversed` with code 040, 000 or 001.

The callback is unsigned, so it is a hint. A callback that reports a reversal of a delivered airtime or data quote
queues one requery of it; any other callback is handled as before, so a reversal before delivery is the failure it
always was. Only a requery that answers reversed moves anything, and nothing polls delivered quotes. Then one batch
moves the quote `settled → reversed` and, for a wallet-paid quote, writes the `refund` of what its hold took, whose
`WHERE` requires the quote reversed and paid from the wallet; a trigger lets a settled quote become nothing but
reversed, and a reversed one nothing at all. A quote paid at the checkout is reversed too, audited `refund.due`,
and refunded through Paystack as a `refund_due` quote is (Refunds, below); it stays `reversed`. A reversed quote is
told as `quote.finished` with state `reversed`, and no longer counts against the day's limits.

## Refunds

A quote paid at the Paystack checkout that then ends owing its payer, an order that failed after payment
(`refund_due`) or one its provider reversed after delivery (`reversed`), is refunded through Paystack's Refund
API, its whole amount, once (`checkout/src/checkout/refunds/`, `checkout/migrations/0019_quote_refund.sql`). A
wallet-paid quote is refunded to the wallet instead (Spending, above) and never reaches Paystack, and a transfer is
never paid at the checkout, so it owes no Paystack refund.

Paystack's documents used: the Refund API (https://paystack.com/docs/api/refund/: `POST /refund` with
`transaction`, a reference or id, `amount` in kobo, at most the transaction's, `currency`, `merchant_note`,
`customer_note`; `GET /refund/:id`; `GET /refund?transaction=` the transaction's id), refunds and their events
(https://paystack.com/docs/payments/refunds/: `refund.pending`, `refund.processing`, `refund.needs-attention`,
`refund.failed`, `refund.processed`, whose data names the payment by `transaction_reference`; `needs-attention`
asks for the payer's bank account; a processed refund can take up to ten business days to reach the payer), and
the statuses of December 2021 (https://paystack.com/docs/changelog/api: a failed refund is credited back to the
merchant). Paystack documents no idempotency key for a refund, so 234 makes the send once itself:

* **Opened once, paid only:** the quote's payment is asked about first (`GET /transaction/verify`), and only a
  success of exactly the quote's amount in NGN is refunded. Then one INSERT, keyed by the quote, whose WHERE holds
  the quote still owing, paid at the checkout and not from the wallet, for that amount under that reference, is
  the claim to send: of any number of callers only the one whose row landed sends. A payment Paystack does not
  hold as such is recorded `refused`, and nothing is sent.
* **Never sent twice:** the row is written before Paystack is called. A send whose answer was lost keeps its claim
  (`sending_since`) and stays undecided; it is sent again only when 234 holds no Paystack refund id for it,
  Paystack lists no refund of the transaction, and the lost send is a minute old. An unanswered list is never
  read as none.
* **Decided by Paystack alone:** `processed` and `failed` decide it, and a decided refund stays decided, by
  trigger; `needs-attention` and anything else leave it undecided. A processed refund ends a `refund_due` quote
  `refunded` in the same batch (a trigger allows `refunded` only from `refund_due`, only with a processed refund,
  and keeps it); `refunded` is told as `quote.finished` and no longer counts against the day's limits. A reversed
  quote stays `reversed`.
* **Followed:** a quote that ends owing asks for its refund as a job at once; Paystack's signed refund event is a
  hint that asks Paystack (`GET /refund/:id`, or the list by transaction) about an undecided refund; the minute
  opens any owed refund never started and asks about every undecided one, at most 50 of each a run.

The card says where the money is: "Refunding ₦500", "Refunded ₦500", "Refund delayed" (Paystack needs the payer's
account), "Refund failed" or "Refund due" (refused), the last three with "234 will follow up." A failed refund is
audited `refund.failed`. What only an operator can finish is listed at `GET /ops/refunds` (holding `OPS_TOKEN`;
`checkout/src/checkout/refunds/attention.py`), newest first: a refund that failed, that 234 refused, that Paystack
holds for the payer's bank account, or that a quote has owed for a quarter of an hour without it being opened; the
reconciliation report counts them and their amount (`refundsNeedingAnOperator`). The simulated Paystack queues a
refund `pending` and never refunds more than the payment. Where the test routes are on, it moves a payment's
refunds on, with the signed event, only from them
(`POST /test/paystack-refund/<reference>?status=processed|failed|needs-attention|processing`); where they are off,
as on a deployed simulated stack, it processes a refund the first time 234 asks about it.

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

234 knows no legal name for an account (a sign-in gives an email and a name the person chose), so the person
matches the name: the wallet card shows the name the bank gives for the account, and Withdraw sends that name
back; the money is taken only when it is exactly the resolved name, and `name_confirmed_at` records when.
Withdrawals are blocked while `wallet_withdrawal_block` holds an unlifted row for the owner
(`wallet/withdrawal_block.py`); an open dispute holds one (see Disputes).

A Paystack account that asks for a one-time code on transfers leaves every withdrawal undecided (234 cannot
type the code for a person), so withdrawals need transfer OTP turned off on 234's Paystack account.

## Disputes

A card top-up can be charged back. Bachs sends `dispute.created` and `dispute.updated`, signed as
`collection.succeeded` is, naming the charge; a credited top-up keeps its `charge_id`, so a dispute finds the
top-up and its owner by it. Bachs takes the disputed amount from 234 at once and charges 234 a $15 fee, which
234 bears; the wallet is never charged it.

* **Held, always:** the dispute's row (`wallet_dispute`, keyed by Bachs' dispute id), then a `dispute` entry
  keyed by the same id, of what the wallet has, up to the disputed amount, worked out in the statement that
  writes it. A wallet never goes below ₦0; an empty one gets no entry.
* **No withdrawals while it is open:** a `wallet_withdrawal_block` row with reason `dispute`. Spending inside 234
  goes on.
* **Frozen only when the hold falls short:** a `wallet_freeze` row for the dispute, until it ends. Freezes are rows,
  each lifted on its own, so a dispute ending never unfreezes a wallet frozen for something else; `wallet.frozen`
  stays the operations' own flag (`wallet/freeze.py`).
* **Won or closed:** a `dispute_back` entry gives back exactly what the hold took. **Lost or prevented:** the hold
  stays, and what it could not cover is 234's loss, `written_off_kobo` on the dispute, for the reconciliation.
  Every ending lifts the dispute's block and freeze.

Events come more than once and in any order (an update before its `created`), so 234 acts on the status each
event carries: every event first opens the dispute if it is not open, then applies a final status, all in one D1
batch whose statements each hold their own rule (`wallet/disputes.py`). A dispute is held once, decided once,
and a late `created` after the decision does nothing. A dispute naming no credited top-up's charge, in another
currency, or for more than the top-up is audited and holds nothing, and Bachs is answered 2xx.

## Where the money is, and the float

The sum of all wallets is what 234 owes. The money arrives in 234's Bachs balance; 234 pays VTpass and Paystack from
their own balances, and **234 tops those up** from its Bachs settlements. The ledger does not move that money; it
tracks the debt, so the code reconciles the two (Reconciliation, below). Who tops up the providers, and how often, is
operations.

## Reconciliation

Once an hour the minute cron, and an operator at any time with `GET /ops/wallet/reconcile` (holding `OPS_TOKEN`),
sets what 234 owes against what it holds (`checkout/src/checkout/wallet/reconciliation.py`):

* **Owed** is the signed sum of the whole journal, every wallet together (`wallet/books.py`); a hold on a quote not
  yet paid is already out of it.
* **Held** is 234's NGN at Bachs, available and pending together, and a lost dispute can take it below zero
  (`GET /v1/balances`, https://docs.bachs.io/connect/balances); at Paystack (`GET /balance`), which pays
  withdrawals; and at VTpass (its balance check), which pays airtime and data (`wallet/treasury.py`).
* **The gap** is owed less held. A provider that cannot be read is unknown, never zero, and is audited
  (`wallet.reconcile.unread`); the run then has no gap.

Each run is kept as it was in `wallet_reconciliation` (`checkout/migrations/0018_wallet_reconciliation.sql`), so the
report is also the history. A run that read every provider and found a gap is **short**: it is audited
`wallet.reconcile.short`, and while the latest such run is short, new top-ups are refused with `FUNDING_PAUSED`
(`wallet/funding_pause.py`, in the WHERE of the statement that opens one), as money taken into a treasury that does
not cover what it owes only adds to what it cannot pay. Spending and withdrawing go on. A run that could not read a
provider neither pauses nor lifts; the next complete run that is not short lifts the pause.

The report also shows what is being withdrawn (taken from wallets, not yet settled by Paystack, so still in its
balance) and the disputes as 234's cost: how many (Bachs' $15 each), how many are open and for how much, and what
lost or prevented ones could not hold, written off. The simulated providers report what they hold: Bachs what its
paid checkouts collected, Paystack and VTpass a float.

## Corrections

An operator corrects a wallet with `POST /ops/wallet/adjust` on the connectors Worker, holding `OPS_TOKEN` as a
bearer token (unset, every `/ops/` call is answered 404). The body names the owner, `credit` or `debit`, the
amount in kobo, a reason (at most 500 characters), the operator's name, and a `correction_id` the operator
chooses. The money moves as one `adjust` entry with that id as its ref, which the wallet card shows as
"Correction". A debit never overdraws and never leaves a frozen wallet; a credit is not capped.

The id writes once: a retry is answered with the first result, and the same id with other terms (owner,
direction, amount, reason) is refused. Above `WALLET_ADJUST_TWO_OPERATORS_KOBO` (default NGN 50,000) the first
call records a proposal and moves nothing; a second call with the same id and terms from another operator
moves the money. Every proposal, correction and refusal is audited with the operator and the reason.

## Safety limits

Wallet balance cap (`WALLET_BALANCE_CAP_KOBO`, default NGN 200,000), per-withdrawal and daily withdrawal caps
(`WALLET_WITHDRAWAL_KOBO`, NGN 50,000; `WALLET_WITHDRAWALS_DAILY_KOBO`, NGN 100,000), all set by 234, a freeze per wallet
(the operations' flag, or a dispute's), and every existing limit of
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
   A hold orphaned by a crash between hold and claim is given back by the reaper of step 6.
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
   A credit the cap refuses for good (past Bachs' retries) is held at Bachs and owed to no wallet, so the
   reconciliation shows it only as more held than owed: an operator credits it with a correction (Corrections).
   Not yet: the re-check of a top-up whose webhook never arrives waits on whether Bachs offers a lookup by checkout.
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
   offers no wallet to an outside OAuth client (`oauth/resources.py`). An account's system prompt names the wallet
   card among what 234 does and the tool's description says the rest; anyone else's prompt says a wallet needs
   signing in (`turns/prompt.py`). Tests `checkout/tests/test_wallet_{connector,approval_card}.py`,
   `host/tests/test_wallet.py`, `conformance/card-states.mjs` (the offer on the card) and
   `conformance/chat-wallet.mjs` (signed in: add money on the simulated Bachs page, pay airtime from the
   wallet, the balance goes down); guards `checkout/tools/mutations/wallet_card_rules.py`. Withdrawing is
   step 5. A guest of a shared chat sees "Pay from wallet" on an approval card the owner made, never the
   balance, and any wallet call of theirs is refused.
5. **Built, simulated.** Withdrawal through Paystack, on the wallet card alone: the model has no tool that
   starts or approves one. `checkout/migrations/0014_wallet_withdrawal.sql` (`wallet_withdrawal`: open →
   sent → succeeded | failed | reversed, open → expired; a decided withdrawal stays decided, and a success may
   only become reversed, by trigger; `wallet_withdrawal_block`). `checkout/src/checkout/wallet/withdrawals.py`:
   `start_withdrawal` (card) checks the caps, the balance, the freeze and the block early, resolves the
   account with the transfer flow's lookup (`flows/holder.py`, `bank_choice.py`), makes the Paystack
   recipient and opens the withdrawal, its token (HMAC of the id with the approval secret) in `_meta` only;
   `withdraw` (card) checks the token, then one batch: the `withdraw` entry (ref = the withdrawal id), one
   INSERT whose WHERE holds the owner's open, unexpired withdrawal, the amount and name the card showed, the
   per-withdrawal cap, the unfrozen and unblocked wallet, the balance, and today's withdrawals (Lagos day,
   less what came back) within the daily cap; then `open → sent` only while that entry exists. Only the call
   that moved it sends the transfer, with the withdrawal id as its reference. `wallet/withdrawal_outcome.py`:
   success settles it; failed or reversed changes the state and writes `withdraw_back` in one batch, once; a
   timeout or `pending` leaves it `sent`. Paystack's `transfer.*` events (`provider_hooks/paystack.py`,
   `references.py`) and the minute's sweep (`provider_hooks/rechecks.py`) ask Paystack about the reference;
   a withdrawal Paystack never answered for and has no transfer of is sent again under the same reference by
   one caller at a time (`sending_since`). `wallet/withdrawal_refusal.py` says why one was refused. The
   connector's tools are in `connectors/wallet.py` and `wallet_withdraw.py`; the card (`card/wallet/`) has
   Withdraw (amount, bank, account number, Next; the bank's name, Withdraw) and says Withdrawn or Returned.
   Tests `checkout/tests/test_wallet_withdraw*.py`, `test_wallet_withdrawal_{races,outcomes}.py`,
   `conformance/chat-wallet.mjs` (withdraw on the card, the balance and the history); guards
   `checkout/tools/mutations/withdrawal_rules.py`.
6. **Built, simulated: disputes, reversals, the reaper, corrections, metrics and the reconciliation.** The
   reconciliation (Reconciliation, above): `checkout/migrations/0018_wallet_reconciliation.sql`,
   `wallet/{books,treasury,reconciliation,funding_pause}.py`, the Bachs and Paystack balances
   (`bachs/client.py` `ngn_balance`, `paystack/client.py` `ngn_balance`, and their simulators), the minute cron and
   `GET /ops/wallet/reconcile` (`ops.py`). Tests `checkout/tests/test_wallet_reconciliation.py`, the balance tests in
   `test_bachs_client.py` and `test_paystack_client.py`; guards `checkout/tools/mutations/reconciliation_rules.py`.
   **Disputes:** `checkout/migrations/0015_wallet_dispute.sql`
   (`wallet_topup.charge_id`; the journal rebuilt with `dispute` and `dispute_back`, keeping its rows, seq, index
   and triggers; `wallet_freeze`; `wallet_dispute`, whose terms are kept and whose decision is final, by
   trigger); `checkout/src/checkout/bachs/disputes.py` (the events), `wallet/disputes.py` (open and decide, one
   batch per event), `wallet/freeze.py` (one SQL rule for "not frozen", held by every debit, top-up and
   withdrawal), `topup_credit.py` (keeps the charge). The simulated Bachs raises and decides a dispute on a paid
   checkout through `POST /test/bachs-dispute/<checkout>?event=…&status=…&amount=…` (test routes only,
   `sim_bachs_dispute.py`), signed through the same hook. The card says "Held for a dispute", "Returned after a
   dispute" and "Withdrawals paused for a dispute." Tests `checkout/tests/test_wallet_dispute*.py`,
   `test_bachs_sim_dispute.py`, `conformance/chat-wallet.mjs`; guards `checkout/tools/mutations/dispute_rules.py`.
   **Reversals are built, simulated** (Reversals, above): `checkout/migrations/0016_quote_reversed.sql` (the
   `reversed` state, rebuilding `quotes` with every row and trigger kept; `sim_vtpass.reversed_at`),
   `checkout/src/checkout/flows/reversal.py`, `vtpass/interpret.py` (the outcome's `reversed`),
   `provider_hooks/{vtpass,rechecks}.py` (the callback's hint, one requery), and `wallet/spending.py`
   (`reversal_refund`). The simulated VTpass reverses a delivered order and sends the callback from the test
   routes alone (`POST /test/vtpass-reverse/<request id>`). Tests `checkout/tests/test_flow_airtime_reversal.py`,
   `test_reversal_migration.py`; guards `checkout/tools/mutations/reversal_rules.py`.
   **Refunds are built, simulated** (Refunds, above): `checkout/migrations/0019_quote_refund.sql` (`quote_refund`,
   the `refunded` state, rebuilding `quotes` with every row and trigger kept; `sim_refunds`),
   `checkout/src/checkout/refunds/`, `paystack/{api,client,sim,sim_store}.py` (the Refund API),
   `provider_hooks/{paystack,http,rechecks}.py` (the refund events and the minute), `sim_paystack_refund.py` (the
   test route). Tests `checkout/tests/test_refund*.py`, `test_paystack_refunds.py`; guards
   `checkout/tools/mutations/refund_rules.py`.
   The reaper
   (`checkout/src/checkout/wallet/stale_holds.py`, run by the minute cron): a `spend` entry at least five
   minutes old (`HOLD_STALE_MS`) with no `release` and whose quote is not marked paid from the wallet is given
   back by `WalletSpending.release`, so a claim that lands late and the reaper exclude each other in SQL;
   oldest first, at most 50 a run, each audited `wallet.hold.released_stale`. A hold and its claim are a few
   statements of one request, so five minutes is far past a live approval, and shorter than the quote's
   ten-minute TTL so the money comes back while the person may still try again with the checkout.
   Corrections (see Corrections): `checkout/migrations/0017_wallet_adjustment.sql` (`wallet_adjustment`:
   proposed → applied, keyed by the correction id), `wallet/correction.py` (the body and its terms),
   `wallet/adjustments.py` (one batch: the `adjust` entry, guarded by the balance and the freeze as
   journal.py's debit, by the threshold, and by the proposal's terms and another operator; then the record,
   only while that entry exists) and `ops.py` (the route and `OPS_TOKEN`, compared in constant time). Metrics:
   one Analytics Engine data point per wallet movement (`checkout/src/checkout/metrics.py`,
   [metrics.md](metrics.md)). Tests `checkout/tests/test_wallet_{stale_holds,adjust,metrics}.py`; guards
   `checkout/tools/mutations/wallet_ops_rules.py`.
7. **Measured, with the real model** (`openai.gpt-oss-120b`, 2026-10-11; [evaluation/RESULTS.md](../evaluation/RESULTS.md),
   Wallet phase). 23 cases (`evaluation/cases.jsonl`, splits `wallet` and `wallet-held-out`), scored by code
   (`evaluation/wallet_score.py`), each draw a new account funded through the simulated Bachs top-up
   (`evaluation/wallet_setup.py`). Held-out: 37 of 45 draws, no dangerous failure (no card tool called by the
   model, no claim that wallet money moved, no balance no tool gave, the injected source obeyed in none). What
   fails: a wallet that does not cover the airtime is not said so (the card offers only the checkout), and a
   withdrawal is sometimes offered in words instead of on the card. A visitor's payment cases are unchanged
   (199/231 against 196); an account's are 191 and 199 against 207 on the same accounts without the wallet,
   mostly INJ-02 (with the tool the model asks before quoting an injected payment) and UNS-05 ("my account
   balance" answered with the wallet's).

## Decided (2026-10-10)

Treasury model: payments into 234's Bachs account, balances in 234's ledger. 234 bears Bachs' collection fee, sets
the caps, and tops up Paystack and VTpass. No BVN for a wallet.

Disputes on card top-ups (2026-10-11): the disputed amount is always held in the wallet; withdrawals are blocked
while a dispute is open, spending inside 234 is not; the wallet is frozen only when it cannot cover the hold; no
wallet goes below ₦0, and a shortfall on a lost dispute is 234's loss, written off in the reconciliation; 234 pays
Bachs' $15 dispute fee. Built (see Disputes; getlatentic/planning#641).

## Still open before real money

- **The licence for holding people's balances.** Bachs' public pages state none for itself and list wallets and money
  transmission among unsupported businesses: ask Bachs in writing whether this use is accepted, and which licence
  covers 234 holding balances for people.

## Not copied from elsewhere

From a public "build a digital wallet" series (2021): card numbers never pass through 234 (Paystack's own page takes
them); a payment is credited from a verified webhook or a re-check, never from the charge's first answer; the amount
credited is the provider's, never one the caller sends; no provider call happens inside an open database transaction.
