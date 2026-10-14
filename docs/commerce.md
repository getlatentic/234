# 234 Commerce: find, price, approve and pay for anything the same way

**Design; nothing here is built yet (see Build order).** One protocol for what a person can buy through 234:
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
| **Merchant** | `id`, `provider`, `name`, `category` (`food`, `airtime`, `data`, `tv`, `electricity`, `shop`), `status` (`live`, `beta`, `coming_soon`: only the first two can be quoted), `requires_link` (the person must connect an account first), `blurb` (234's own words on when to choose it: never the merchant's), `limits` (least and most per order, in kobo), `fields` (what the buyer must give: a smartcard or meter number, a phone, an address). |
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
2026-10-13, over a third of a short request). The connector adds six tools, and the free-text `create_payment_quote`
and the food tools go when their merchants move into the directory, so the total does not grow by six. Every
description is measured on the evaluation before it ships (evaluation/README.md).

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

## Build order

1. This document, and the board (milestone "234 · Commerce").
2. **The core**: the merchant and offer tables, the provider interface, `browse_merchants`, `find_items`,
   `check_account`, `track_order`, `create_quote`, the card for a basket; the simulated directory (Mama Put moved
   onto it); the live-mode guard on the free-text payment tool.
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
