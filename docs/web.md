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
offered only where a search gateway is set up. The index is Amazon Bedrock AgentCore's managed **Web Search tool**
($7 per 1,000 searches, no minimum), reached through an AgentCore Gateway in the owner's AWS account over MCP; 234
runs outside AWS and calls the gateway with IAM (SigV4, `web/sigv4.py`, checked against AWS's published test
vector). The Web Search tool is offered in **us-east-1** only.

- **Set up** (`tools/aws-search.sh`, `infra/aws/web-search.yaml`): `up` makes the gateway, its web-search target
  and one IAM user that may invoke that gateway and nothing else; `key` makes that user's access key and keeps it in
  `.env.search.local` (mode 600, git-ignored; nothing is printed); `secrets` puts `SEARCH_GATEWAY_URL`,
  `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` into the connectors Worker's secrets; `down` removes it all.
- **Off until set:** with any of the three missing or malformed the connector offers `web_fetch` alone, and the
  Worker's log says why (`web.search.off`). Setting the secrets one at a time never stops the payment connectors.
- **Cost control:** a person has `SEARCHES_PER_DAY` (30) searches, counted in one statement before the search is
  made (`web_search_use`); the same question within the hour is answered from the cache and costs none; a turn
  makes three calls to sources at most (`SEARCHES_PER_TURN`), and a research run twelve. At $0.007 a search the
  worst case for a person's day is about $0.21.
- **What a result is:** a snippet and an address, never a page. An address that is not https or not public is
  dropped; the model reads a result with `web_fetch`, which obeys robots.txt. The host shows the sources an
  answer draws on, as it does for the sources and the web.

## Not built yet

Pages that need JavaScript (Browser Rendering).
The crawler's name in the User-Agent, `234bot/1.0 (+https://234.getlatentic.com)`, is a placeholder until the
contact page exists.
