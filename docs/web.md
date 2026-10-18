# Reading a web page

The `web` connector has one read-only tool, `web_fetch(url)`: the text of one page, quoted as data with its
address and the day it was read. It is for a page the person names or a source points to. Code:
`checkout/src/checkout/web/` and `connectors/web.py`; it runs in the connectors Worker.

## What it will read

- an `https` address by public name: no IP address in any spelling, no login in the address, no port but 443, no
  `localhost`, `*.local`, `*.internal` and the like (`web/safe_url.py`);
- a site that is not on the deny list. `workers.dev` is always on it; `WEB_DENY` adds sites (comma-separated, with
  their subdomains). `WEB_ENABLED=0` switches the tool off;
- a page its site's `robots.txt` allows for `234bot` (RFC 9309: a missing file allows, a server that fails does not);
- at most three redirects, each address checked again; at most 2 MB; web pages and plain text only.

A page becomes its title and the words of its body (`web/extract.py`): scripts, styles, menus, forms and frames
are left out, and no link is kept. The text is cut at 24,000 characters, about 6,000 tokens, and says so. A page
and a `robots.txt` are kept for an hour (`web_cache`, migration 0009).

## What the model does with it

The page's lines are quoted behind `>` under a header of ours with its address and day. The result says
`untrusted: true`, and the host records `untrusted` on the tool event (`turns/sources.py`):

- a turn may make three calls to sources (`knowledge` and `web` together; `SEARCHES_PER_TURN`);
- once a turn has read a source, it calls nothing that changes something until the person writes again, so a page
  cannot steer a payment, a transfer, an order or a note. The approval card still guards every payment;
- the passages of an earlier question are not sent to the model again;
- the compaction summary sees only that a tool answered, never what it said;
- a link or an amount in the answer that no source (and not the person) gave is named to the person.

## Searching the web

`web_search(query, limit)` finds pages: titles, addresses, dates and snippets, quoted as data like a page. It is
offered only where `SEARCH_API_KEY` is set. The index is **DeepSeek's Search API**
(`POST https://api.deepseek.com/v1/tools/search`, the key as a bearer token; $0.75 per 1,000 searches that return
results, 5 requests a second for the account, HTTP 429 above that, 402 when the balance is empty). 234 sends `query`
and `count` and nothing else.

- **What leaves 234:** the text of the search query, sent to DeepSeek. No name, account, chat or note goes with it.
  The model writes the query, so a person's words can be in it.
- **Query:** at most 128 characters (the API refuses a longer one), so the client cuts it there, and the tool
  asks the model for 128 at most. The API reads `site:`, `-site:`, `lang:`, `after:`, `before:` and quoted phrases.
- **Set up:** put the key on the connectors Worker, piped in so it is never printed or kept in a shell history,
  on staging first and then on production:
  `jq -r .deepseek.apiKey ~/.viva/auth.json | STAGE=staging tools/deploy.sh secret connectors SEARCH_API_KEY`, then
  the same without `STAGE=staging`. `SEARCH_URL` may name another path on `api.deepseek.com` (https only and no
  other host, because the key goes there); `SEARCHES_PER_DAY` changes the daily count. Locally,
  `SEARCH=1 SEARCH_API_KEY=... tools/up.sh` calls the real API.
- **Off until set:** with no key, or a malformed `SEARCH_API_KEY`, `SEARCH_URL` or `SEARCHES_PER_DAY`, the
  connector offers `web_fetch` alone, and the Worker's log says why (`web.search.off`). Setting the secret never
  stops the payment connectors.
- **When it fails:** a timeout, 402, 408, 429, a 5xx, or a reply that is not the expected JSON gives the model
  `SEARCH_UNAVAILABLE` (it says search did not answer and does not answer from memory). The call is made once; the
  person's search still counts.
- **Cost control:** a person has `SEARCHES_PER_DAY` (30) searches, counted in one statement before the search is
  made (`web_search_use`); the same question within the hour is answered from the cache and costs none; a turn
  makes three calls to sources at most (`SEARCHES_PER_TURN`), and a research run twelve. At $0.00075 a search the
  worst case for a person's day is about $0.02. A busy minute can pass 5 requests a second; the excess is
  refused with `SEARCH_UNAVAILABLE`, not queued.
- **What a result is:** a snippet (the start of the summary when the snippet is a fragment) and an address, never
  a page. A result's date counts only as an ISO day (`2026-09-01`); the API's `None` is no date. Results keep the order
  the API gives them: 234 does not filter or re-rank by the API's authority and relevance scores. An address that is not https or not public is
  dropped; the model reads a result with `web_fetch`, which obeys robots.txt. The host shows a result or a page as a
  source under an answer only when its text holds a figure of the answer (or, for an answer with none, when its
  words clearly carry it), as it does for the sources: [knowledge.md](knowledge.md#what-the-person-sees). A snippet
  is short, so a figure that a search result's snippet does not hold is not credited to it; `web_fetch` the page
  and the whole text is checked.

## Not built yet

Pages that need JavaScript (Browser Rendering).
The crawler's name in the User-Agent, `234bot/1.0 (+https://234.getlatentic.com)`, is a placeholder until the
contact page exists.
