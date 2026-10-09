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

## Not built yet

Pages that need JavaScript (Browser Rendering) and the search tool (#572, which needs a Brave Search API key).
The crawler's name in the User-Agent, `234bot/1.0 (+https://234.getlatentic.com)`, is a placeholder until the
contact page exists.
