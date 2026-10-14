# 234 Commerce: find, price, approve and pay for anything the same way

**Design; the core (build step 2) is built, simulated, and measured with the real model (see "What is built" and Build order).** One protocol for what a person can buy through 234:
search a directory of merchants, see what they sell, have the server price it, approve it on a card, pay it from
the wallet (or at the checkout), and follow the order to its end. Airtime and data stay as they are until the
generic path measures as well. Bills (DSTV, electricity) are the first merchants of the directory, served by
VTpass. A person's own Paystack Index account is a second kind of provider. Merchants 234 onboards itself are a
third, last, because they need a business partner and a licence answer first (docs/wallet.md).

It is built from what exists, and says where it differs:

* **Paystack Index's ten tools** (read 2026-10-13 from its MCP server, `index.mcp.paystack.africa`): six read
  (`browse_merchants`, `find_items`, `track_order`, `get_balance`, `get_recent_activity`, `find_beneficiaries`) and
  four act (`quick_buy`, `order`, `request_transfer_approval`, `connect_merchant`). Its merchants carry a status
  (`live`, `beta`, `coming_soon`), `requires_link` and a `blurb` written for assistants; its purchases are
  two-phase (a preview that moves nothing, then `confirmed=true`).
* **Google's Universal Commerce Protocol** (ucp.dev): `catalog` (search, lookup), `cart`, `checkout` (a session
  whose totals the business computes), `order` (webhook status updates), an MCP binding for each, payment handlers,
  and an AP2 mandates extension.
* **What 234 has**: the quote, its approval card, the wallet's hold, claim and release, VTpass requery and
  reversal, refunds, `quote.finished` events, PACT sign-in at other Brands.

**Where it differs from Index.** Index leaves the gate to the agent: "the gate that protects the user is YOU", and
a `confirmed=true` argument spends. Here the gate is the person, on the card, and no tool the model can call
spends. A model that is talked into anything can only make a quote.

## The words

| | |
|---|---|
| **Provider** | The code that lists merchants, prices an order and fulfils it: `vtpass` (bills), `directory` (merchants 234 onboards), `index` (a person's own Paystack Index account). One interface (Providers, below). |
| **Merchant** | `id`, `provider`, `name`, `category` (`food`, `grocery`, `health`, `shop`, `service`, `airtime`, `data`, `tv`, `electricity`), `status` (`live`, `beta`, `coming_soon`: only the first two can be quoted), `requires_link` (the person must connect an account first), `blurb` (234's own words on when to choose it: never the merchant's), `limits` (least and most per order, in kobo), `fields` (what the buyer must give: a smartcard or meter number, a phone, an address). |
| **Offer** | What a merchant sells: `id`, `merchant_id`, `name`, `price` (`fixed` kobo, a `range` with least and most, or `open` within the merchant's limits), `available`, option groups. A listed price is indicative. |
| **Account check** | A provider's look-up of what the buyer typed: a smartcard, a meter. It returns the holder's name and what is due, and an id that the quote must carry. A wrong meter number cannot be undone, so the card shows the holder's name for the person to confirm, as a transfer shows the bank's. |
| **Basket** | Lines of `{offer_id, quantity, options}` and the fulfilment fields. The model sends ids and counts and never a price. |
| **Quote** | The existing quote, made for a merchant: authoritative totals (items, fees, delivery, 234's service fee, total), the account check's holder name, an expiry, and a hash of all of it. The approval is bound to the hash. |
| **Order** | A quote's life after approval: paid, fulfilled, failed, reversed, refunded. The quote's states, as built. |

## The tools (one connector, `merchants`)

Read-only (no card, no money):

| Tool | What it does | Index / UCP |
|---|---|---|
| `browse_merchants(category?)` | The directory: id, name, category, status, `requires_link`, `blurb`. | `browse_merchants` |
| `find_items(merchant_id, query?, offer_id?)` | Search a merchant's offers, or look one up, or list all of them. Text only, no photos. | `find_items`; `catalog.search`, `catalog.lookup` |
| `check_account(merchant_id, fields)` | The account check. Calls the provider (VTpass `merchant-verify`); changes nothing. | `quick_buy` phase 1 |
| `track_order(quote_id)` | Where the order stands: paid, delivered, pending, reversed, refunded. | `track_order`; `order` |

Acting (a card, never a spend):

| Tool | What it does | Index / UCP |
|---|---|---|
| `create_quote(merchant_id, lines or amount, fields, check_id?)` | Prices the order on the server and shows the approval card. It buys nothing. The model may pass an `amount` only for an `open` or `range` offer, within the limits. | `quick_buy`, `order`; `cart`, `checkout` |
| `connect_account(merchant_id)` | Opens a card in which the person connects their own account (sign in at Index; the Chowdeck phone and its SMS code). The code and the tokens are typed into the card and never pass through the model. | `connect_merchant` |

The wallet's balance and history are the wallet tool and card, as built. Index's `find_beneficiaries`,
`request_transfer_approval` and `get_balance` have no counterpart: transfers are the `send-money` connector.

**Tool budget.** The tool definitions are sent with every turn (about 14,000 characters for 15 tools on
2026-10-13, over a third of a short request). The connector adds five tools (`connect_account` is step 4, and
`track_order` is the connector's status tool, not one more beside `get_quote_status`), 5,204 characters on
2026-10-14, 19,195 characters for the 19 tools the model was offered before it (the memory, knowledge, web and wallet
tools had been added since the 15). The free-text `create_payment_quote` and the food tools go when their merchants
move into the directory, so the total does not grow by five. Every description is measured on the evaluation before
it ships (evaluation/README.md; RESULTS.md, "Commerce phase").

## A purchase, end to end (DSTV)

1. The person: "renew my DSTV, smartcard 7012345678". The model calls `browse_merchants("tv")` and
   `find_items("dstv")` to name the bouquets, or the person names one.
2. `check_account("dstv", {smartcard})`: VTpass confirms the card and returns the holder's name, the current
   bouquet and the renewal amount. The tool returns a `check_id`.
3. `create_quote("dstv", offer_id, check_id)`: the price comes from the offer, not the model. The card shows
   DSTV, the holder's name, the bouquet, the total and the fee, and "Pay from wallet" as for airtime.
4. The person approves. The wallet's `spend` is held, the quote is claimed, and 234 pays VTpass from its own VTpass
   balance with a request id derived from the quote (docs/wallet.md, "Spending"). A reply that is not clearly
   delivered or failed is pending and is asked about again; it is never paid twice.
5. Delivered: the receipt. Electricity's prepaid token is on the receipt and in the reply. Failed or reversed after
   delivery: the wallet is refunded, once, as for airtime.

## Providers

One interface, so a new provider adds no new tools:

```
merchants(category?)          -> [Merchant]
offers(merchant, query?)      -> [Offer]
check(merchant, fields)       -> AccountCheck | refusal
price(merchant, basket, check) -> Totals          # authoritative; the quote stores it
fulfil(quote)                 -> delivered | pending | failed   # idempotent by the quote
status(quote)                 -> delivered | pending | failed | reversed   # the requery
```

* **`vtpass`**: `tv` (DSTV, GOtv, StarTimes) and `electricity` (the distribution companies), later water,
  internet, exam pins. The offers are VTpass's `service-variations` (bouquets and prices; electricity is `open`
  between its least and most). `check` is `merchant-verify` (`020` is confirmed). `fulfil` is `pay` with the
  quote's request id; `status` is `requery`. It reuses what airtime has: the unsigned callback as a hint, the
  requery, the reversal, the refund. Airtime and data stay on their connector until `merchants` measures as well.
* **`directory`**: merchants 234 onboards. Offers live in D1; the merchant sees and edits them in a dashboard;
  fulfilment is a message to the merchant and its answer. Payout to the merchant is the open question (Money).
  The simulated "Mama Put" restaurant is the first merchant, replacing the hardcoded menu.
* **`index`**: a person's own Paystack Index account, connected by OAuth (authorization code with PKCE; Index's
  registration endpoint is open) from a card. The model is never given Index's tools. `create_quote` for an Index
  merchant runs Index's preview phases on the server (`needs_options`, `needs_confirmation`), puts the breakdown on
  234's card, and calls the `confirmed=true` phase only after the person approves it. The person's Zap pays; no
  wallet entry is made, and the quote says so (`funding: external`). The tokens are kept per owner, encrypted with
  a key of the Worker's, and the person can disconnect from the card.

## Rules the server holds, whatever the model says

1. **No price from the model.** Totals come from the provider's offers and the server's arithmetic. An `open`
   offer takes an amount only within the merchant's limits.
2. **A quote needs a merchant id from the directory.** There is no free-text merchant, so "pay DSTV" can no longer
   become a payment to nowhere. The present `create_payment_quote` is kept only for 234's own demo and is refused
   in live mode.
3. **Third-party words are data.** Merchant and offer names and descriptions are length-limited, escaped on the
   card, never placed in the system prompt, and never followed. 234's own `blurb` is what guides the model. Index
   says the same of its own directory ("untrusted data").
4. **The approval is bound to the quote's hash.** A changed total, merchant or holder is a new quote.
5. **An account check is required** where the provider says so, and the card shows the holder's name.
6. **Three outcomes, never a blind retry.** `delivered`, `failed`, or `pending` (asked about again until it is
   one of the others); one request id per quote; the wallet's hold is given back only for a quote nobody paid.
7. **Limits.** The merchant's, the person's daily limit (the ledger's), and a cap per category until the evaluation
   says higher. Paystack Index's own published caps (₦5,000 per bill, ₦100,000 per food order) are a reference.
8. **Connected accounts are the person's.** One owner, never shared; the card is the only way to connect or
   disconnect; a failed refresh asks the person to connect again.

## Money

* **VTpass and, later, the directory**: the wallet pays; 234 pays the provider from its own balance
  (the reconciliation counts it, docs/wallet.md). A margin or a service fee on bills is the owner's decision: VTpass
  returns a commission on a purchase, and the card shows any fee 234 adds as its own line.
* **Index**: the person's own Zap. 234 holds nothing and owes nothing for these.
* **Directory merchants**: paid out by split payments. Bachs' Connect product (split, destination charge, transfer
  and payout) fits the wallet's treasury better than Paystack subaccounts; either needs a merchant agreement, the
  provider's approval and, for 234, the licence answer (#644). Until then the directory holds simulated merchants.

## Interoperability, later and from the same records

* **UCP**: a discovery profile at `/.well-known/ucp` for the directory; `find_items` as `catalog.search` and
  `catalog.lookup`; `create_quote` and the card as `checkout`; `track_order` and `quote.finished` as `order`.
  The version is negotiated, as ucp.dev says to.
* **ACP**: a product feed export for directory merchants. Its checkout is cards through Stripe, Adyen or Braintree,
  so it is not a checkout for Naira.
* **AP2**: signed mandates for a standing instruction ("buy ₦20,000 of electricity monthly for this meter"). The
  quote hash and the person's approval are the same idea for one purchase; recurring is a design of its own.

## What is built (the core, simulated)

`checkout/migrations/0020_commerce.sql` (the tables) and `0021_commerce_directory.sql` (the simulated directory);
`checkout/src/checkout/commerce/` (the provider interface, the registry, the `directory` provider, pricing,
options, fields, account checks, the model-facing lists and the third-party text rules);
`connectors/merchants.py`, `flows/merchants.py`, `flows/merchant_leg.py`; the basket on the approval card
(`card/static/card.js`); the test route `POST /test/merchant-order/<quote id>?outcome=delivered|pending|failed`
(`sim_merchant_order.py`); `FREE_TEXT_MERCHANTS` (`config.py`). Tests `checkout/tests/test_commerce_*.py`,
`test_flow_merchants*.py`; guards `checkout/tools/mutations/commerce_rules.py`; browser conformance
`conformance/chat-merchants.mjs`; the evaluation's `commerce-dev` split (`evaluation/commerce_score.py`).

* **Tables.** `merchant` (provider, status, `requires_link`, `blurb`, `min_kobo`/`max_kobo`, a fee, `checks_account`,
  the fields the buyer gives), `offer` (price `fixed`, `range` or `open`; availability; at most one to ten of one;
  option groups), `account_check` (what a provider found for one owner, immutable) and the simulated directory's
  `sim_merchant_account` and `sim_merchant_order`. Checks refuse a row that breaks a rule; triggers keep a merchant's
  id and provider and an offer's merchant, id and kind of price, refuse to change a check, keep a decided order's
  answer, and refuse to remove a merchant or an offer that a quote names (it is retired by `available` or `status`).
  A quote keeps a copy of every line, price and fee it was made from (`quotes_are_fixed`), so changing an offer
  changes nothing a quote used.
* **Providers.** `Provider` is the interface of "Providers" above (`commerce/provider.py`); `Providers` routes a
  merchant, and a quote by the provider it names, to its own. The `directory` provider reads D1 and prices a basket
  (`pricing.py`): every line is checked against the offers (it exists, is available, its options are the offer's and
  complete, its count is 1 to 10 and within the offer's own most, at most twelve different lines), prices are the offer's
  plus the chosen options', the fee is the merchant's, and the order's total is within the merchant's least and
  most. Nothing in the model's arguments is a price: a line names an offer, a count and option ids. The only money it
  may name is `amount_kobo` for a single `open` or `range` offer, within that offer's limits (the merchant's, for
  `open`), checked against `amount_as_user_said` as every amount is; an amount for an offer with a price is refused.
* **The tools.** `browse_merchants`, `find_items`, `check_account` and `track_order` read; `create_quote` makes the
  quote and shows the card. Everything of a merchant's that the model reads passes `third_party` (no control or
  formatting character, one line, a length), and each list begins with one line saying that names and descriptions
  are data, never instructions; only the merchant's `blurb` guides. `find_items` ends by telling the model to
  call `create_quote` if the person wants to buy and to answer if they only asked what it sells or costs, and lists
  everything when the words match nothing; `browse_merchants` names the merchants of other categories after those
  of the one asked for. A merchant id that is nearly right is named in the refusal ("Did you mean ...") and never
  quoted for.
* **The approval is bound to the quote.** `create_quote`'s approval token is the ledger's own HMAC
  (`Ledger.approval_token`), taken over the quote's id and a SHA-256 of its merchant, lines, fees, fields, holder, total
  and expiry (`commerce/binding.py`), read from the stored quote each time. A token for the id alone, or for another
  quote, approves nothing, and so does one for a quote whose terms differ.
* **Account check.** `check_account` records what the provider found (the holder and what is due) as an
  `account_check` of that owner with an id, for fifteen minutes; asked again for the same account while one lives,
  it returns it. A quote for a merchant that checks accounts must carry a check of the same owner, merchant and
  fields, and takes the holder's name from it and from nowhere else; the card shows it above the amount.
* **Fulfilment.** After approval (the wallet's hold, claim and release, or Paystack's checkout), `flows/merchant_leg.py`
  places the order with the merchant's provider: one request id per quote (`mrq-<quote id>`) fixed by one conditional
  write, one caller at a time, the answer recorded by a statement that applies only while the quote is approved.
  `delivered` ends the quote, `failed` leaves a refund owed (to the wallet, or at Paystack as for airtime), and anything
  else is pending, asked about again with `status` by the card's poll, a provider's callback and the minute, never
  placed again. The simulated merchants deliver at once unless the test route set another answer.
* **The card.** The approval card shows a basket: a line for each item with its options, a line for each fee, the
  buyer's fields, the total, the merchant and the holder's name. The receipt lists the same.
* **Wallet and checkout.** The same as airtime: "Pay from wallet" is offered to an account whose wallet covers it, the
  checkout otherwise; a refused order is refunded to the wallet or Paystack once. `create_quote` takes `from_wallet`
  as the airtime tools do.
* **`FREE_TEXT_MERCHANTS`** (default on while Paystack, VTpass and Bachs are simulated or in a sandbox) gates the free-text
  `create_payment_quote`: off, the tool is not offered and the flow refuses; on beside a provider that is neither
  simulated nor in a sandbox, the Worker refuses to start (docs/deploy.md).

**Where the design was silent, or differs.**

* A provider's `check` returns what it found (`AccountLookup`); the core keeps it as an `AccountCheck` with an id and an
  expiry, so every provider's checks are held and expire the same way. `Provider.merchant(id)` was added for routing.
* `create_quote(merchant_id, lines, amount_kobo, amount_as_user_said, fields, check_id, from_wallet, idempotency_key)`:
  `lines or amount` is `lines`, or an `amount_kobo` alone for a merchant with one `open` offer; an open or range offer
  stands alone in its basket, paid once.
* A quote that carries a `check_id` and no `fields` is for the account that check was made for (the check holds its
  fields, and is the owner's, the merchant's and immutable); with `fields` they must still match the check.
  `browse_merchants` ends a merchant's line with the fields its buyer gives and says when `check_account` comes first
  ("Needs card_number, after check_account."), and a missing field is refused with the shape to pass it. Without
  these a model that never listed the offers called `check_account` with no fields, then asked the person for the card
  number they had typed.
* The merchant's limits are on the order's total, fees included; for an `open` offer the amount is also within them.
* The categories are the design's and three more (`grocery`, `health`, `service`) for the simulated directory.
* `track_order` is the connector's status tool: the connector has no `get_quote_status`, and its quotes tell the
  model to report with `track_order`.
* `connect_account` and the `index` and `vtpass` providers are steps 3 and 4. A merchant that `requires_link`, or
  that is `coming_soon`, is listed and cannot be quoted.
* The simulated directory is four invented merchants (Mama Put, the restaurant of `food/menu.py`, whose menu is
  listed here with the same ids, names, prices and tags and checked equal by a test for as long as both exist; a
  pharmacy; a grocer; and a transit card whose accounts the merchant checks and whose top-up takes any amount), all
  named "(simulated)". They are rows in D1, not a deployed business: before real money a merchant row is real or it is
  gone. The first draft of the service was a water meter; the prompt does not pay bills (step 3), and the model
  declined it as one.
* The existing connectors (`food-order`, `airtime`, `send-money`, `paystack-pay`) are as they were. Mama Put is in both
  places until `merchants` measures as well on the evaluation.
* Not built: reversal of a delivered merchant order (the reversal flow is airtime's), refund by a provider other than
  the wallet and Paystack, the dashboard, payouts, UCP and ACP.

## Which deployment offers the directory

The host offers `merchants` only where `MERCHANTS` says so (`1`, `true`, `on` or `yes`; `host/src/turns/settings.py`,
`with_directory`). **Default: off**, in the code and in the public template (`host/wrangler.public.jsonc`), which still lists
the connector in `CONNECTORS`; a local stack (`tools/up.sh`) turns it on. The reason is a measured conflict
(evaluation/RESULTS.md, "Commerce phase, second part"):

* **Directory on, free-text payment off** (`MERCHANTS=1`, `FREE_TEXT_MERCHANTS=0`, `paystack-pay` left out of `CONNECTORS`):
  the intended production setting. On the cases that do not pay a merchant named in words it passes as the old
  connectors do (every split within the spread of two runs of the same code), and it adds what the directory is for.
* **Directory on, free-text payment on**: the model is told to look in the merchant list before it says a business is not
  offered, so "Pay ₦2,200 to Ada Stores" now goes to the directory and is declined: 6 of 15 and 5 of 15 draws of the dev
  cases that pay a named business pass, and 8 of 15 of the wallet ones, against 15 of 15 without the directory.
* **Directory off, free-text payment on**: the product as it was before #677. The public deployment keeps this while its
  starter ("Pay ₦2,500 to Ada Stores") and the scripted model's `pay <amount> to <merchant>` intent are the free-text
  path.

So the two are switched together: a deployment that moves to the directory sets `MERCHANTS=1` and
`FREE_TEXT_MERCHANTS=0` and drops `paystack-pay` from `CONNECTORS` (docs/deploy.md). Before that, the starter and the
cases that pay a named business change: a directory merchant takes the place of "Ada Stores" (a transit top-up with a card
number, or a basket), and the scripted model keeps its `pay` intent for the free-text stack only. The evaluation skips the
cases that need the free-text tool when `FREE_TEXT_MERCHANTS` is `0` in its environment (`Case.needs_free_text`:
`create_payment_quote` expected, or an allowance used up first, which the harness does with that tool).

## Build order

1. This document, and the board (milestone "234 · Commerce"). **Done.**
2. **The core**: the merchant and offer tables, the provider interface, `browse_merchants`, `find_items`,
   `check_account`, `track_order`, `create_quote`, the card for a basket; the simulated directory (Mama Put moved
   onto it); the live-mode guard on the free-text payment tool. **Built, simulated** (getlatentic/planning#677; "What
   is built"), and measured with `openai.gpt-oss-120b` on development cases (evaluation/RESULTS.md, "Commerce phase").
3. **Bills on VTpass**: tv and electricity providers, the account check, receipts with a token, the evaluation
   cases (the DSTV case becomes a purchase).
4. **Index as a per-user connector**: OAuth with registration, the connect card, the server-side phases, the
   evaluation.
5. **Directory merchants and payouts**: the dashboard, fulfilment, split payments (owner decisions first).
6. **Interoperability**: the UCP profile, the ACP feed.
7. **Fresh held-out cases** for commerce (the earlier splits have been run too often to be a clean test).

## Open before real money

* **The first real directory merchant**, and who handles its refunds and disputes.
* **Margin on bills**, and whether the card says so.
* **How a platform may hold Index connections**: the per-user OAuth route is open; one account for many people
  needs Paystack's answer (the Terms do not cover it).
* **Caps**: which Index and VTpass limits apply to 234's accounts; one small purchase of each shows it.
