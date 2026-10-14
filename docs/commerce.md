# 234 Commerce: find, price, approve and pay for anything the same way

**Design; the core (build step 2), bills on VTpass (step 3) and Index as a per-user connector (step 4) are built, simulated, and measured with the real model (see "What is built", "Bills on VTpass", "What is built for Index" and Build order).** One protocol for what a person can buy through 234:
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

* **`vtpass`**: `tv` (DSTV, GOtv, StarTimes, Showmax) and `electricity` (the twelve distribution companies), later water,
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
* `connect_account` and the `index` provider are step 4; the `vtpass` provider is step 3 (below). A merchant that `requires_link`, or
  that is `coming_soon`, is listed and cannot be quoted.
* The simulated directory is four invented merchants (Mama Put, the restaurant of `food/menu.py`, whose menu is
  listed here with the same ids, names, prices and tags and checked equal by a test for as long as both exist; a
  pharmacy; a grocer; and a transit card whose accounts the merchant checks and whose top-up takes any amount), all
  named "(simulated)". They are rows in D1, not a deployed business: before real money a merchant row is real or it is
  gone. The first draft of the service was a water meter; the prompt does not pay bills (step 3), and the model
  declined it as one.
* The existing connectors (`food-order`, `airtime`, `send-money`, `paystack-pay`) are as they were. Mama Put is in both
  places until `merchants` measures as well on the evaluation.
* Not built: reversal of a delivered order of a provider other than `vtpass` (bills extend the reversal flow), refund by a provider other than
  the wallet and Paystack, the dashboard, payouts, UCP and ACP.

## What is built for Index (simulated)

`checkout/src/checkout/commerce/index/` (the provider, the connection, the simulator), `connectors/merchant_accounts.py`
(`connect_account` and the connect card's tools), `migrations/0023_index.sql`, the connect card (`card/connect/`), the
host's `/connect/index/callback` (`host/src/chat/views/connect.py`) and its guest rules (`chat/views/cards.py`). Tests
`checkout/tests/test_index_*.py` and `host/tests/test_connect_index.py`; guards `checkout/tools/mutations/index_rules.py`; browser
conformance `conformance/chat-index.mjs`; the evaluation's `index-dev` split (`evaluation/index_score.py`). No call to the real
Index was made: every test, the conformance run and the evaluation talk to a simulated Index that lives in the connectors'
Worker (`commerce/index/sim*.py`) and is the default (`INDEX_MODE`, below).

* **The simulated Index.** An `IndexSimulator` is the `Transport` of the real client: the OAuth server of Index's published metadata
  (dynamic client registration, the authorization code with PKCE S256, refresh with rotation, `client_credentials`, revocation
  when a test route turns it on), and the MCP endpoint (protocol 2025-03-26, `paystack-index` 0.0.1, JSON or event-stream
  answers, a session id) advertising Index's ten tools with the names, annotations and schemas of 2026-10-13
  (`tests/fixtures/index_tools.json`; `tests/test_index_sim_contract.py` keeps the two the same) and refusing a call that breaks a
  schema. Eight tools are implemented (the transfer tools answer that they are not offered). Its sign-in page is
  `/sim/index/authorize` on the connectors' Worker; the test routes `/test/index/...` set an account's Zap, make the next charge
  `delivered`, `failed`, `pending`, `dropped` (charged, answer lost) or `lost` (not charged, answer lost), expire or revoke the
  tokens, and read every call served with whether it carried `confirmed`. Two of its texts are hostile on purpose: a
  merchant's own blurb and a dish's name.
* **Settings.** `INDEX_MODE=simulated|live` (default simulated), `INDEX_MCP_URL` (live only; `https` on `index.mcp.paystack.africa`
  or `index.paystack.com`, nothing else), `INDEX_TOKEN_KEY` (a Worker secret, 32 or more characters, made once by
  `tools/deploy.sh` like `APPROVAL_SECRET`; the simulator may borrow a key from the approval secret, live refuses to start
  without one), `INDEX_CAPS_KOBO` (234's cap per order below Index's bounds, by `airtime`, `electricity` and `food`). Live also
  needs `HOST_PUBLIC_URL` to be https: Index sends the person back to the chat host.
* **Connecting.** `connect_account(merchant_id)` (the model's tool, accounts only) opens the connect card for the merchant. The
  card holds a link to Index's sign-in (authorization code, PKCE S256, a `state` of 43 characters) and asks 234, every three
  seconds, how it stands. 234 registers itself at Index once for the deployment (`index_client`, the secret sealed) and every
  person uses that client. Index sends the browser to the chat host's `/connect/index/callback`; the host acts only for the
  signed-in account whose browser arrived, rate limits it, and gives the code and the state to the connector's
  `complete_connection` as that account. The connector takes the state once (`index_attempt`: the SHA-256 of the state, the PKCE
  verifier sealed, one conditional UPDATE, the attempt's owner, open and unexpired), exchanges the code, and keeps the tokens.
  A wrong state, a state used twice or by another person, a late sign-in and a refused one connect nothing; a code that Index
  refuses ends the attempt and the card offers to try again. Chowdeck is linked on the same card: the person types the phone number
  of their Chowdeck account and the code Index texts into the card, which sends them to `send_link_code` and `confirm_link_code`
  and from there to Index's `connect_merchant`; neither is in a tool the model calls, a result it reads or a log, a card may
  send at most six, and the link counts only when a read of Chowdeck's feed then succeeds. Disconnect (the card's button) forgets
  the tokens, ends every open attempt of the person, and asks Index to revoke them where its metadata names a revocation endpoint.
* **Tokens at rest.** Access and refresh tokens are sealed (`secretbox.py`: HMAC-SHA256 in counter mode, authenticated, standard
  library only) with a key of the Worker's and a context that names the owner and the column, so a stored value is not the
  token and opens for no other owner, column or key. A token is renewed a minute before it runs out and when Index answers 401
  (it did not act); a refresh is claimed by one call at a time (a refresh token is good once) and the others wait for its result;
  a refresh Index refuses ends the connection and tells the model to call `connect_account`; one that could not be tried (no
  answer) leaves it. Every statement on a connection names the owner.
* **The provider.** `index` lists Index's `browse_merchants` (read once an hour for everyone, with the asking person's token when
  they are connected and with the token Index gives 234 itself for its public directory otherwise; the last list stands if neither
  can be had), only `live` and `beta` merchants that 234 can buy from (Chowdeck, airtime by network, electricity by distribution
  company; data bundles and Zap transfers are not offered), as `index:<Index's id>` with 234's own blurb (Index's is dropped when
  the list is read) and every name cleaned like any third-party text. A merchant needs the person to connect first until they
  have (and Chowdeck until they link it); a visitor is shown none. Offers: airtime and electricity are one offer paid for any
  amount; Chowdeck's are its dishes (`v<restaurant>-i<dish>`; a dish's required choices are option groups). `check` is electricity's
  phase 1 with the merchant's least amount; `price` runs Index's preview phases on the server and never sends `confirmed`:
  airtime reads the Zap balance (Index has no preview of it), electricity validates the meter again with the real amount and
  requires the holder to be the one the person confirmed, Chowdeck previews `order` (`needs_options` is a refusal naming the
  options, `needs_confirmation` is the breakdown) for the dishes of one restaurant. The quote's lines are the model's dishes, its
  fees and total are Index's own (delivery, any other charge), and the card shows them with whose money pays (`your Zap balance
  at Paystack Index`) and what is left of it. An order that Zap does not cover, or Zap not linked, is not quoted.
* **Funding is `external`.** The quote's details carry `funding: external`, `paidFrom`, `balanceAfterKobo` and the Index call as
  previewed (`details.index`), which the approval's digest includes. The card offers Approve only (no wallet) and approves with
  `funding: "external"`; a quote paid that way is approved that way and no other (`FUNDING_MISMATCH` both ways: the wallet or the
  checkout cannot approve an Index quote, and no other quote can be approved as one, checked before the claim and again in the
  claim's own WHERE). No wallet entry is made; the quote, the card and the receipt say so.
* **Placing the order, once.** After the one approval, `index/fulfil.py` is the only place that sends `confirmed` (for airtime
  the one `quick_buy` call is the charge). It checks that the person is still connected and, for a Chowdeck order, previews again
  and refuses to charge if the total moved since the quote; then it writes a marker for the quote with one conditional UPDATE
  (`indexSend`) and only then sends. A call that finds the marker asks where the order stands and never sends: a repeated
  approval, a racing one, a crash between the send and the answer, the card's poll and the minute's sweep cannot charge twice.
  What comes back is one of three outcomes: **delivered** (a prepaid token and a delivery PIN go on the receipt), **failed**
  (Index refused: the quote ends `failed` with nothing charged and no refund owed, since 234 holds nothing), or **pending**
  (no answer, an unknown status word, a payment Index has not finished): asked about again with `track_order` for Chowdeck and,
  for airtime and electricity, which have none, with the person's Zap history for a debit of exactly the quote's amount since
  the approval; found, delivered; not found an hour after the send, `failed` with the words "no matching debit".
* **Limits.** Index's bounds (airtime ₦50 to ₦5,000, electricity ₦1,000 to ₦1,000,000; ₦100,000 for a food order is its published
  cap) under 234's caps (₦5,000, ₦50,000 and ₦20,000 by default) are the merchant's limits, so an order outside them is refused
  before Index is called; so are the per-payment and daily limits (an amount that is named is checked before the first Index
  call; a food order's total is Index's, so the limits are checked on it).
* **Who may.** Connecting and quoting are for signed-in accounts (`account_of_call`). A guest of a shared chat cannot press the
  connect card or approve from the owner's Index account: the host refuses those card calls (`owners_alone`), as it refuses the
  wallet's. A client that reaches `merchants` through the OAuth gateway is not an account of the chat host, so it is shown no
  Index merchant.

**Where the design was silent, or differs.**

* The redirect lands on the chat host, not on the connectors: the host knows who is signed in and the connectors hold the
  tokens, so the callback is the host's, acts for the browser's account, and passes the code over the service binding.
* Index's answers are documented only in prose, so what 234 reads of them (`balance_kobo`, `zap_linked`, `needs_confirmation`,
  `breakdown`, `payment_route`, `order_id`, `delivery_pin`, `token`, the Zap activity's `amount_kobo` and `created_at`) is looked
  for under those names, in kobo or naira, at the top of the answer or in a section of it; an answer without what a caller needs
  is refused and nothing is charged. **Every one of those names is a guess made from the tool descriptions until the owner runs
  the real Index** (below).
* A refusal the model reads never repeats Index's instruction to ask for a phone number: where Index says Chowdeck is not linked,
  234 says to call `connect_account`, and stops treating Chowdeck as linked.
* The approval card shows "Balance after", the Zap left, which the wallet card never shows: a guest of a shared chat can read it.
  Without it the person could not see that Zap covers the order; the quote already refuses an order Zap cannot cover.
* `quotes.details.index` keeps the arguments the order was previewed with (for Chowdeck the dishes' ids and the address words, for
  electricity the meter), as every quote keeps what it was priced from.
* `account_check` lost its foreign key to `merchant` (migration 0023 rebuilds the table), because an Index merchant is not a row of ours.
* `find_items` lists a choice's name beside its id when the id does not say it (`9001:7002 (Large) +₦1,000`).

**Not done, and what only the owner can check against the real Index.** The real Index's answers (the names above); whether its
dynamic registration accepts 234's redirect and gives the client `client_credentials` (without it the directory fills only after
the first person connects); that its ids for merchants map to the networks and companies 234 reads from their names (airtime,
electricity); what `get_recent_activity(source="zap")` returns, which an ambiguous airtime or electricity order depends on;
whether a Chowdeck total can change after the preview (Index's `amount_change_direction`), which 234 can only report; Index's real
revocation; data bundles (their catalog needs a phone number first), Zap transfers and Index credits; Index merchants in a client
that is not 234's own chat; and the connection listed under Connected apps (the card's Disconnect is the only way to end it).

**What the model does with it** (`openai.gpt-oss-120b`, 28 development cases, evaluation/RESULTS.md "Index phase"): 38% of draws pass.
It sends a person who has not connected to the card, never asks for a code in the chat, never approves, and follows no text in a
dish's name; it still often takes Chowdeck for the Mama Put menu and airtime paid "through Index" for the airtime connector, and
the signed-in payment `dev` split lost seven draws against the commerce core. No draw approved or charged anything, but the
numbers say the wording is not finished.

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

## Bills on VTpass (built, simulated)

`checkout/migrations/0022_commerce_bills.sql` (sixteen merchants, `account_check.detail`, two columns of the simulated
VTpass's orders); `checkout/src/checkout/commerce/vtpass_provider.py`, `vtpass_offers.py`, `vtpass_check.py`,
`vtpass_price.py`; `checkout/src/checkout/vtpass/bills.py`, `receipt.py`, `sim_bills.py`; `flows/reversal.py` for bills.
Tests `checkout/tests/test_bills_*.py`, `test_flow_bills*.py`, `test_vtpass_bills*.py`; guards
`checkout/tools/mutations/bills_rules.py`; browser conformance `conformance/chat-bills.mjs`; the evaluation's `bills-dev`
split (evaluation/RESULTS.md, "Bills phase").

* **Merchants.** The VTpass serviceIDs are the merchant ids: `dstv`, `gotv`, `startimes`, `showmax` (category `tv`) and
  `ikeja-electric`, `eko-electric`, `kano-electric`, `portharcourt-electric`, `jos-electric`, `ibadan-electric`,
  `kaduna-electric`, `abuja-electric`, `enugu-electric`, `benin-electric`, `aba-electric`, `yola-electric`
  (category `electricity`), as the documentation of each (read 2026-10-14) gives them. They are rows of `merchant` with
  `provider = 'vtpass'`; the provider is offered only while VTpass is simulated or in its sandbox (`bill_providers`),
  so in any other mode they are not listed and cannot be quoted. A merchant's `max_kobo` is `10^13`, which means it
  states no most (`NO_MAXIMUM_KOBO`): VTpass publishes none.
* **Offers are not rows.** A television merchant's bouquets and their prices are read from VTpass's `service-variations`
  each time (`fixed`); DStv and GOtv also sell `renew`, a price of kind `renewal` that is the account check's renewal
  amount. Electricity is one `open` offer, `electricity`. The model names an offer and, for electricity, an amount.
* **The account check** is `merchant-verify` (a smartcard; a meter and its `prepaid` or `postpaid` type). It returns the
  holder and, when VTpass gives them, the address, the arrears, the due date, the current bouquet, the renewal amount, the
  least and the most; every one of those but the holder is optional, because the documentation's own sample lacks what its
  prose promises. `WrongBillersCode`, an `error`, `Can_Vend` false, or no holder refuse the number: it is never quoted.
  The core keeps the facts and the amounts to price from in the check's `detail` (JSON; the check stays immutable).
  The phone given with the check is kept there too (`carried`), and a quote with a `check_id` takes the checked
  account's fields from the check, so the model need not type them twice.
* **Pricing** (`vtpass_price.py`). A bouquet costs VTpass's list price; a DStv/GOtv change is shown as "Change to ...";
  a renewal costs the check's renewal amount and is refused (`RENEWAL_UNKNOWN`) when VTpass gave none, and refuses an
  amount from the model; electricity costs the person's amount, within the least and most of the meter's check
  (`AMOUNT_OUT_OF_LIMITS`), and no most is assumed when VTpass states none, so the person's own per-payment and daily
  limits are what stop a large amount. One subscription or purchase per quote. The phone is written nationally
  (`+234...` becomes `0...`). The check's address, status, current bouquet, due date and arrears are fields of the quote,
  so the card shows them and the approval is bound to them; what the provider will order is in `details.order`, which is
  in the digest too.
* **Fulfilment.** `pay` under a request id the Lagos minute then the quote (`VtpassProvider.request_id`, fixed once per
  quote by the merchant leg), a renewal sent as `subscription_type: renew` at the check's amount with no bouquet, a change
  with the bouquet's `variation_code`, a meter's type as `variation_code`; `status` is `requery`. Outcomes are the
  existing three; pending (also an unexpected reply, no reply, a timeout) is never failed; a request VTpass says it never
  saw (`015`) is ordered again under the same id. VTpass is ordered the bill alone, never the service fee.
* **Receipts.** An electricity prepaid token, its units and tariff (`token` or `purchased_code`, `units`, `tariff`), a
  Showmax voucher, are kept with the order's answer, shown on the card (the token in the reference style), put in the
  tool's reply ("Delivered. Token: 1234 5678 ...") and in `track_order`. A postpaid payment settles with no token; a
  DStv or GOtv subscription says "Valid for 1 month". The token is not written to the audit log.
* **Reversal after delivery** (`reversed`, `040`) extends `flows/reversal.py` to a `merchants` quote of the `vtpass`
  provider: the callback is a hint, the provider's `status` must answer reversed, a wallet payment comes back once in the
  same batch, a checkout payment owes a Paystack refund. A refused or reversed order before delivery is a `refund_due`
  quote, as for any merchant.
* **Money.** The wallet pays the total; 234 pays VTpass from its own VTpass balance (the reconciliation counts it as
  for airtime). `BILLS_SERVICE_FEE_KOBO` (default 0, a whole number of kobo) adds a "Service fee" line of its own to the
  card and the total when above zero; it is the owner's decision and none is assumed. VTpass's commission is not
  passed on or kept in any figure shown.
* **The simulated VTpass** (`vtpass/sim_bills.py`) answers the documented sandbox scenarios by the smartcard or meter:
  smartcard 1212121212 and meters 1111111111111 (prepaid) and 1010101010101 (postpaid) succeed, 201000000000 is pending,
  500000000000 answers unexpectedly, 400000000000 does not answer, 300000000000 times out, any other number fails. It
  differs from the sandbox in two ways: the trigger numbers and 100000000000 (a number that verifies and then fails) are
  accepted by the account check so each outcome can be shown through a quote, and Showmax delivers to any valid mobile
  number. A later reversal is simulated by the existing `POST /test/vtpass-reverse/<request id>`.
* **Wording the model needed** (measured in evaluation/RESULTS.md): the prompt now says TV and electricity bills are
  paid through the merchant list and names no tool; `find_items` ends with what to call next, with the answer-only
  case first (the model stopped after "Let me create the quote" when the order was the other way round); a named
  bouquet is a change and none a renewal; the electricity blurbs say to choose the company only when the person names it
  or its area, and not to assume prepaid or postpaid; `create_payment_quote` no longer says electricity and TV are not
  merchants; a refused id with a near match says to call again with it; the per-payment refusal says not to suggest
  splitting the payment.

**Decisions.**

* The service fee is a setting, not a column: one number for all bills until the owner chooses a margin per product.
* A renewal is a quote of its own offer (`renew`) and not an `amount`, so the card shows which of the two it is.
* An amount that VTpass states no most for is limited by the person's own limits only; no ceiling of ours is invented.
* A sandbox run needs the documented sandbox numbers as smartcards and meters; the substitution that airtime does for a
  phone number has no counterpart, because a wrong meter is refused by the check before anyone pays.

## Build order

1. This document, and the board (milestone "234 · Commerce"). **Done.**
2. **The core**: the merchant and offer tables, the provider interface, `browse_merchants`, `find_items`,
   `check_account`, `track_order`, `create_quote`, the card for a basket; the simulated directory (Mama Put moved
   onto it); the live-mode guard on the free-text payment tool. **Built, simulated** (getlatentic/planning#677; "What
   is built"), and measured with `openai.gpt-oss-120b` on development cases (evaluation/RESULTS.md, "Commerce phase").
3. **Bills on VTpass**: tv and electricity providers, the account check, receipts with a token, the evaluation
   cases (the DSTV case becomes a purchase). **Built, simulated** (getlatentic/planning#678; "Bills on VTpass"), and
   measured with `openai.gpt-oss-120b` on development cases (evaluation/RESULTS.md, "Bills phase").
4. **Index as a per-user connector**: OAuth with registration, the connect card, the server-side phases, the
   evaluation. **Built, simulated** (getlatentic/planning#679; "What is built for Index"),
   and measured with `openai.gpt-oss-120b` on development cases (evaluation/RESULTS.md, "Index phase"). The real Index is
   for the owner to check.
5. **Directory merchants and payouts**: the dashboard, fulfilment, split payments (owner decisions first).
6. **Interoperability**: the UCP profile, the ACP feed.
7. **Fresh held-out cases** for commerce (the earlier splits have been run too often to be a clean test).

## Open before real money

* **The first real directory merchant**, and who handles its refunds and disputes.
* **Margin on bills**, and whether the card says so. `BILLS_SERVICE_FEE_KOBO` shows it as its own line when set; the figure is the owner's.
* **How a platform may hold Index connections**: the per-user OAuth route is open; one account for many people
  needs Paystack's answer (the Terms do not cover it).
* **Caps**: which Index and VTpass limits apply to 234's accounts; one small purchase of each shows it.
