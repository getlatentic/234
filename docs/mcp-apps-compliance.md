# MCP Apps: what the standard asks of a web host, and what this host does

The chat host is a web page, so the standard's "Sandbox proxy" section applies to it in full. This page says what the standard requires, what the host, the sandbox Worker, the connectors and the cards do about each rule, what differs between the revisions of the standard and of MCP itself, and what was not verified. Every claim that names a test can be run from the repository; how is at the end.

## Sources and the revisions compared

- **MCP Apps (ext-apps).** `specification/2026-01-26/apps.mdx`, the stable revision, and `specification/draft/apps.mdx`, in `modelcontextprotocol/ext-apps`. The repository holds no other revision of the specification. The TypeScript SDK in use is `@modelcontextprotocol/ext-apps` 2.0.3 (its `AppBridge` and `App` are the oracle: the host is built on the first, and one of the cards on the second).
- **MCP itself.** Revision `2025-11-25` (the handshake era: `initialize`, sessions) and revision `2026-07-28` (the stateless era: `server/discover`, no handshake, per-request `_meta`), from `modelcontextprotocol.io/specification/2026-07-28`. Python `mcp` 2.2 and `@modelcontextprotocol/client` 2.2 are the official clients used as oracles for the connectors.
- **The reference host.** `examples/basic-host` in the ext-apps repository (its `sandbox.ts` and `serve.ts`), read for how the sandbox proxy is meant to be built.

## What the standard requires of a web host, and what is done

"Sandbox proxy", rules 1 to 8, then the security section.

| # | Rule | Here |
|---|---|---|
| 1 | Host and sandbox have different origins | The sandbox is its own Worker on its own hostname (`<sandbox-worker>.<your-subdomain>.workers.dev`; locally `127.0.0.1:PORT+5` against the hosts on `localhost`). `conformance/sandbox-proxy.mjs` checks the origins differ, and that the host's cookie and `localStorage` are unreadable in the proxy, no request to the sandbox carries a cookie, and the proxy cannot reach the host document. See "One site, two origins" for what workers.dev cannot give. |
| 2 | Sandbox has `allow-scripts` and `allow-same-origin` | The frame in the chat page is `<iframe sandbox="allow-scripts allow-same-origin">` (`_item.html`). |
| 3 | Proxy sends `ui/notifications/sandbox-proxy-ready` | Sent once its script has run, addressed to the host's origin (it is named in the URL as `?host=` and checked against the Worker's `HOST_ORIGINS`). |
| 4 | Host then sends the raw HTML in `sandbox-resource-ready` | `<card-frame>` fetches the card (`GET /c/<chat>/card`, JSON: the HTML and what the host grants) while the proxy loads, waits for the proxy's message, then sends `html`, `sandbox`, `csp`, `permissions`. Nothing is sent to the proxy before its message (`chat-bridge.mjs`). |
| 5 | Proxy loads the HTML under the declared CSP, `frame-src`, `base-uri`, `object-src 'none'`, `allow` from permissions | See "The policy". |
| 6 | Forward everything not `ui/notifications/sandbox-*`, both ways; host sends nothing to the view before `initialized` | The proxy forwards JSON-RPC 2.0 objects both ways and drops sandbox messages, other messages and messages from any other window or origin (`sandbox-proxy.mjs`, 38 checks in all). The host's transport (`sandbox-transport.js`) holds every request or notification the bridge produces until the card's `initialized` has arrived, then sends them in order; only the `ui/initialize` response and sandbox messages pass before (`chat-bridge.mjs` reads the proxy's timeline). |
| 7 | Sandbox does not create requests | It sends the host one notification of its own, `proxy-ready`, and nothing to the view. Checked: the view hears only what the host sent. |
| 8 | Host may forward non-`ui/` messages to the server; may block or ask | `tools/call` from a card goes through the host's relay: only the tools its own view lists, only app-visible tools, only for a card this chat holds. Everything else a view sends (`resources/read`, `ui/download-file`, sampling) is refused because the host does not declare it. |

### Three frames, not two

The reference host puts the view's policy in the header of the proxy page and writes the view into a frame that inherits it. Here the proxy page has a policy of its own, so it cannot carry the view's:

1. **The proxy page** (`GET /?host=<origin>`): a static document whose only script and only style are named in its policy by hash, `default-src 'none'`, `frame-ancestors` the host's origin alone, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, no cookie, no storage, no network of its own. Its script is served as its own source text and refuses to run if it can reach the top window or is the top window.
2. **The view's page** (`GET /view?host=&csp=<json>`), the frame the proxy makes. Its **response headers** carry the view's policy, built from the declaration by the Worker, which validates it again (`sandbox/src/csp.js`). Its inline script waits for the proxy to hand it the HTML and writes it in with `document.open/write/close`. The policy stays in force for what is written, in Chromium and in WebKit (Playwright's engines): an undeclared script is blocked and reported as a violation in both (`sandbox-proxy.mjs`).
3. **The card** is that written document.

If a hash source and `'unsafe-inline'` sit in one policy the browser drops `'unsafe-inline'`, and the specification's policy needs it, so the proxy's own policy could not have been the view's.

### The policy

Built exactly as the specification's "CSP Construction from Metadata" snippet (`sandbox/src/csp.js`, checked directive by directive in `sandbox/test/csp.test.mjs` and in a real browser):

```
default-src 'none'; script-src 'self' 'unsafe-inline' R; style-src 'self' 'unsafe-inline' R;
connect-src 'self' C; img-src 'self' data: R; font-src 'self' R; media-src 'self' data: R;
frame-src F | 'none'; object-src 'none'; base-uri B | 'self'
```

R is `resourceDomains`, C `connectDomains`, F `frameDomains`, B `baseUriDomains`. Two directives are added that the snippet does not have and that only tighten: `form-action 'none'` and `frame-ancestors 'self' <host>` (the chain of ancestors is checked whole, so the host must be named as well as the proxy). With no declaration the policy is the specification's restrictive default plus `object-src 'none'` (which the draft also adds, see below).

`'self'` is the sandbox origin. The sandbox serves nothing a view could read (three static routes), and a view without an origin of its own cannot read it anyway.

### What a resource may declare: validation and the host's allowlist

A resource declares `_meta.ui.csp` on its `resources/read` content or, failing that, on its `resources/list` entry (the draft's "Metadata Location": the content wins, both are checked). The host (`chat/card_csp.py`) cuts the declaration to what it grants:

- Each entry must be `https://host[:port]`, or `wss://` for `connectDomains`; a leading `*.` is the one wildcard; at most 16 per field, repeats folded. Refused: a bare `*`, `data:`, `blob:`, `http:`, `ws:`, a path, query, fragment or credentials, a space, `;`, quote or comma, upper case, an IP address or dotless host, a bad port, a field that is not a list. `sandbox/test/csp-vectors.json` holds 62 entries, run through both validators (Python and JavaScript), which must agree.
- Then the **allowlist** (setting; defence against a compromised connector): the entry must be on the host's own list for that field, or come from a connector in `CARD_IMAGE_SERVERS` (default `food-order`) as a plain origin in `resourceDomains`. The default list is Paystack's two origins, when `INLINE_PAYSTACK` is on (`js.paystack.co` for scripts, `checkout.paystack.com` for frames); `CARD_ALLOWED_ORIGINS` adds origins for every field. Everything else is refused.
- A refused entry is **logged** (`card.csp.refused`, with the connector, the resource, the field and the reason) and never shown; what was granted is logged too (`card.csp`), as the standard asks for an audit trail. In `conformance/inline-checkout.mjs` a connector is made to ask for connections, a wildcard, `data:`, a look-alike frame origin and a foreign base URI: the card gets Paystack's two, the host's log has 14 lines, the page says nothing.
- `hostCapabilities.sandbox.csp` lists what the host approves; `sandbox.permissions` is empty.

**The line.** When a card is granted any origin, one quiet line sits above it: "This card loads content from js.paystack.co and checkout.paystack.com" (three names at most, then "and N more"), a paragraph the person can read before pressing anything, not a dialog (`proxy-domains-*.png`). A card that declares nothing shows nothing.

### The sandbox flags of the view, and permissions

- The view is `sandbox="allow-scripts"`: no origin of its own, so no cookie, no storage, no reach into the proxy or into another card's frame. No forms, popups, modals or navigation.
- A view that embeds an approved third-party frame (it was granted a `frameDomains` entry) gets `allow-scripts allow-same-origin`. This is because Paystack's `inline.js` builds a blank frame and reads its document, which an opaque view is not allowed to do (measured: "Blocked a frame with origin null from accessing a cross-origin frame", and the popup never loads; with the flag it loads in Chromium and WebKit). **The cost is real:** such a view shares the sandbox origin with every proxy frame of the chat and with any other card that has the same flag, so it can script them (`top.frames[n]`): read another same-origin card's DOM, click in it, and post to the host as that card's proxy. What it cannot do: call the host (its own policy has `connect-src 'self'`, and a request to the host needs a CSRF token that only the host's page holds); widen its own policy, because the sandbox serves a view only under a policy the host signed (next item); reach an opaque card's DOM. The only cards that get the flag are those whose resource declares an entry the host's allowlist grants for `frameDomains`, which is Paystack's checkout alone. A compromised connector could declare it, and so could be a scriptable neighbour of a legitimate approval card in the same chat; this is accepted because the alternative is a popup that does not load. Options, cheapest first: turn `INLINE_PAYSTACK` off (no frame origin can be granted, every view is opaque); restrict the grant to named connectors; give each card its own sandbox origin, which workers.dev cannot do (see "`domain`").
- **Signed policies.** The sandbox serves a view's page only with `sig`, the host's HMAC-SHA256 (a key shared by the host and the sandbox Workers: `SANDBOX_SIGNING_KEY` and `SIGNING_KEY`) over the host's origin and the declaration it granted (`sandbox.canonical` and `csp.js canonical`, run against one vector). Without it, or with the signature of another policy, host or key, it answers 403 and logs `view.unsigned`; with no key it answers 503. The proxy's own policy allows frames from its own origin, so a view on the sandbox origin can create a frame of `/view` itself, but it can only obtain policies the host has signed (`sandbox-proxy.mjs` makes a same-origin view try a wider one and is refused). The host signs for `PUBLIC_BASE_URL`; a host without a key shows no card.
- The proxy honours the host's `sandbox` override only for the flags `allow-scripts allow-same-origin allow-forms allow-popups allow-modals`; anything else (top navigation, downloads, ...) is dropped. Nested frames inherit these flags, so the outer frame's are the ceiling.
- **Permissions.** The frame's `allow` is built from what the resource declares **and** the host grants (`CARD_GRANTED_PERMISSIONS`, default none). None is granted: no card copies to the clipboard or uses a camera, a microphone or a location, so there is no reason to give even `clipboard-write`. Paystack's popup asks for `payment`, `clipboard-read` and `clipboard-write` on its own frame; the standard's list has none of the three as a resource permission that maps to `payment`, and none is delegated, so wallet payments and paste inside the popup are unavailable (not tested, since no payment was made).

### `domain`

`_meta.ui.domain` is a request for a dedicated origin (OAuth callbacks, API allowlists; the format is host-specific: Claude derives `{hash}.claudemcpcontent.com`, ChatGPT `…oaiusercontent.com`). This host has **one stable sandbox origin** and does not honour it: the value is logged (`domain_ignored`) and every view runs on that origin (or none, when opaque). None of our cards declares one. To support it, run one sandbox Worker per allowed domain (a custom-domain route each), keep a table `domain -> sandbox origin` beside `SANDBOX_ORIGIN`, choose the origin per card from it in `<card-frame>`, and list the host in each Worker's `HOST_ORIGINS`.

### One site, two origins

Host and sandbox are different origins on different hostnames. On workers.dev they are **not different sites**: `workers.dev` is on the Public Suffix List, so `<host-worker>.<your-subdomain>.workers.dev` and `<sandbox-worker>.<your-subdomain>.workers.dev` share the registrable domain `<your-subdomain>.workers.dev`. What keeps them apart: every cookie the host sets is host-only (none names a `Domain`; a unit test and the deploy smoke test check that), so no cookie reaches the sandbox; storage is per origin; opaque views cannot set cookies at all; the `connect-src` of a same-origin view cannot name the host. The remaining exposure is a view on the sandbox origin (the Paystack card) setting a cookie for `<your-subdomain>.workers.dev` that the host would receive. A different site needs a custom domain for the sandbox. Locally the two are different sites (`localhost` and `127.0.0.1`).

## Host context, capabilities and messages

`ui/initialize` result, checked against what the official `App` reads (`conformance/chat-bridge.mjs`):

| Field | Sent |
|---|---|
| `protocolVersion` | `2026-01-26` (the SDK's latest; it echoes the card's version when it supports it) |
| `hostInfo` | `checkout-host` |
| `hostCapabilities` | `openLinks`, `serverTools`, `logging`, `updateModelContext.text`, `message.text`, `sandbox { permissions: {}, csp: {approved origins} }`. Not declared, because not done: `serverResources`, `downloadFile`, `sampling`, `experimental`. |
| `hostContext.theme` | from `prefers-color-scheme`; a change is sent as `host-context-changed` |
| `hostContext.styles.variables` | 55 of the standard's names as `light-dark(light, dark)`, generated from `design/tokens.json` (colours: background, text, border, ring; type; radii; border width; shadows). The palette has no "info" role, so those names are left out and a card keeps its own default. `styles.css.fonts` is not sent: the only web font is the wordmark's. |
| `displayMode`, `availableDisplayModes` | `inline`; `["inline", "fullscreen"]`. `pip` is not offered. |
| `containerDimensions` | inline: `{maxHeight: 6000, width}`; full screen: `{height, width}` (fixed). Updated on resize. |
| `locale`, `timeZone`, `userAgent` | the browser's, the browser's, the product name |
| `platform`, `deviceCapabilities`, `safeAreaInsets` | `web`; touch and hover; the page's `env(safe-area-inset-*)` in pixels (0 in Chromium) |
| `toolInfo` | not sent (no card uses it) |

| Message | Status |
|---|---|
| `ui/notifications/tool-input` | sent once after `initialized` (`{arguments: {}}`: the card's arguments are the model's and are not shown to it) |
| `ui/notifications/tool-input-partial` | not sent; a card is mounted after the tool has run |
| `ui/notifications/tool-result` | sent after `tool-input`, for the stored result, later states (this tab, another tab, a payment webhook) and the result of a call |
| `ui/notifications/tool-cancelled` | not sent: a card exists only for a call that returned |
| `ui/notifications/host-context-changed` | sent for theme, display mode, frame size, orientation, once the card has initialized. The bridge replaces its context on `setHostContext`, so the host always passes the whole context (a change of display mode once dropped `availableDisplayModes`). |
| `ui/notifications/size-changed` | received; the frame's height follows |
| `ui/resource-teardown` | sent as a request on `pagehide`, while the frame still exists. Removing a frame from the page (a deleted chat is a navigation) leaves nobody to tell. |
| `ui/request-display-mode` | `inline` and `fullscreen`; any other mode, or one the card did not list in `appCapabilities.availableDisplayModes`, gets the current mode back |
| `ui/message`, `ui/update-model-context` | text only; recorded as notes, never with the approval token. Notes have a limit of their own per visitor (12 a minute); messages share the visitor's message limit. A card that repeats itself is refused. |
| `ui/open-link` | web links only, in a new tab (`noopener`), with the chat's address added to the simulated checkout |
| `notifications/message` | logged to the console |
| draft: `ui/download-file`, `ui/notifications/request-teardown`, app-provided tools, `sampling/createMessage` | not supported and not declared (a view's request is refused, a teardown request is ignored, which the draft allows) |

## Differences between the revisions, and what was done

**ext-apps 2026-01-26 to draft** (diff of the two `apps.mdx`):

| Change in the draft | Effect here |
|---|---|
| `_meta.ui` may be on `resources/list` and on the `resources/read` content; the content wins | Both are read (`hub.read_card`), tested. |
| `object-src 'none'` in the restrictive default | Always present. |
| Sandbox proxy messages are SHOULD, not MUST | The host and proxy send them anyway. |
| `HostCapabilities`: `downloadFile`, `updateModelContext` and `message` with content modalities, `sampling`, `experimental` keyed by name | `updateModelContext` and `message` declared as `text`; the others not. |
| `ui/download-file` | Not supported (downloads are blocked in the frame: no `allow-downloads`). |
| `ui/notifications/request-teardown` (view asks to be closed) | Ignored. |
| App-provided tools (`tools/list`, `tools/call` host to app), long-running app tools | Not used: the host does not list tools of a card and the cards declare none. |
| `sampling/createMessage` from a view | Not offered. |
| Example `protocolVersion` `2025-06-18` | Looks stale; the SDK uses `2026-01-26` and so does the host. |

Nothing in the draft changes the sandbox proxy's rules, the CSP construction, permissions or display modes beyond the first two rows.

**MCP 2025-11-25 to 2026-07-28**, for a host and for MCP Apps:

| Change | Connectors | Host's own client (`hub.py`) | Cards |
|---|---|---|---|
| No `initialize`, no `Mcp-Session-Id`; every request carries `_meta` protocolVersion and clientCapabilities and the header `MCP-Protocol-Version` | **Served**, beside the handshake era (`mcp/modern.py`): a request that opens in the new era is answered on its own. Missing `_meta` is invalid params (400); a header that differs from `_meta` is `HeaderMismatch` (-32020, 400); an unknown version is `UnsupportedProtocolVersion` (-32022, 400) naming the supported ones. | Speaks 2025-11-25 (`initialize`, then requests). It talks only to our connectors, which speak both. | n/a |
| `server/discover` | Answered: the versions (this one and the three of the handshake era), capabilities with the `io.modelcontextprotocol/ui` extension and its mime type, instructions, `serverInfo` in `_meta`, `ttlMs`, `cacheScope`. In the handshake era it is still "method not found", so a client that probes falls back as before. | Not used. | n/a |
| `Mcp-Method`, `Mcp-Name` headers, validated against the body (`Mcp-Name` may be `=?base64?…?=`) | Validated for `tools/call` and `resources/read`. No tool uses `x-mcp-header`, so no `Mcp-Param-*` is expected. | n/a | n/a |
| Results carry `resultType`; cacheable ones `ttlMs` and `cacheScope`; `serverInfo` in result `_meta` | All results `complete`; discover, both lists and `resources/read` give `ttlMs` 300000 and `public`. The card-only `_meta` (approval token, access code) is unchanged and `serverInfo` is added beside it. | Ignores the new fields. | n/a |
| Resource not found is -32602, not -32002 | Emitted in the new era; -32002 in the old. | n/a | n/a |
| `ping`, `logging/setLevel`, `resources/subscribe` removed | Not found (404, -32601) in the new era. | Not used. | n/a |
| `_meta.ui` is unchanged by the revision; `extensions` is where `io.modelcontextprotocol/ui` and its `mimeTypes` are negotiated (per request now) | The connectors always emit `_meta.ui`, as the standard's own fallback advice allows: a host that ignores it gets the text content. They do not vary a list by the client's capabilities, which the new revision forbids for cached lists. | Sends the extension in `initialize`. | n/a |
| Sampling, elicitation and roots are no longer server requests: they come back inside an `input_required` result (MRTR), and Sampling, Roots, Logging are deprecated | Never asked: no connector uses them, so no result is `input_required`. | Would need an `input_required` handler if a connector ever asked. | n/a |
| Tasks moved to an extension (`io.modelcontextprotocol/tasks`) | Not used. | Does not advertise it, so no task handle can be returned. | n/a |
| Streamable HTTP: `Origin` must be validated (this holds in the earlier revisions too) | **Was missing.** A request that names an `Origin` is now refused (403) unless `MCP_ALLOWED_ORIGINS` lists it: the callers are servers, which send none. | n/a | n/a |

Checked with the official clients: Python `mcp` 2.2 with `mode` `legacy`, `auto` and `"2026-07-28"` (a client pinned to the new era, which never sends `initialize`), and the TypeScript client with `versionNegotiation: {mode: {pin: "2026-07-28"}}`: list the tools, read the card, run a tool with the approval token in `_meta`. Before this change the pinned clients failed and only `auto` worked, by falling back.

**ext-apps and MCP 2026-07-28.** The ext-apps 2.0.x packages sit on the 2.x MCP SDK and their `ui/*` wire protocol is unchanged from 1.x. Neither ext-apps specification mentions the new MCP revision (an issue in the repository, #742, says the docs do not match it); the UI channel's own version string is independent of the MCP revision.

## The Paystack popup

An option of the approval card for card payments, off wherever it cannot run.

- **Flow.** Approve makes the connector initialize a transaction. In Paystack test mode (`PAYSTACK_PAY_MODE=test`, with a `sk_test_` key: a live key is still refused at startup) the connector keeps the transaction's `access_code` in the ledger and hands it to the card **only in `_meta.paystack.accessCode`**, on `approve_quote` and on `verify_quote` while the person is at the checkout. Never in the text of a result, the model's `get_quote_status`, the audit log, the page's visible text, or what an A2A caller is sent (checked in `test_inline_checkout.py` and `inline-checkout.mjs`). **One exception, stated plainly:** for Paystack's hosted checkout the authorization URL is `https://checkout.paystack.com/<access_code>`, and that URL is already the card's `checkoutUrl` (the card opens it as a link), so it is in the card's stored state, in the chat's event log and in the page's data for that chat, as before this change. `_meta` is therefore not a secret from the chat's own visitor; what it keeps the code out of is the model's text, the A2A view and the structured part of `get_quote_status`. The code is a capability for one unpaid test transaction, exactly as the URL is. The approval card's resource declares `_meta.ui.csp` with `resourceDomains: [js.paystack.co]` and `frameDomains: [checkout.paystack.com]`, only in that mode.
- **Feature detection** (`card/static/inline-checkout.js`). All of: the host lists both origins in `hostCapabilities.sandbox.csp` and offers `fullscreen`; the card holds an access code; the script loads within 8 s; no policy violation is reported while it loads; `new PaystackPop()` works; the host grants full screen (the popup is a frame that fills its window, so it needs the window); the popup reports `onLoad` within 12 s. If anything fails, full screen is left, the popup is closed, the popup is not tried again in that card, and the link opens through `ui/open-link` exactly as before, with nothing for the person to read. Nothing is requested from Paystack before Approve.
- **The server decides.** `onSuccess` only makes the card ask `verify_quote`; a payment is received when the server's own call to Paystack says so (`webhook` for the simulator, `verify_quote` for Paystack). Test: `onSuccess` fired with no payment leaves the card waiting; after the stand-in marks the transaction paid, the receipt shows.
- **Close, cancel, error, second press, reload.** The popup's cancel and the host's Close bar leave full screen and dismiss the popup; nothing is abandoned and Open checkout works again. A popup error after it loaded closes it and opens the link. The card behind a full-screen popup cannot be pressed. After a reload nothing opens by itself; the card is handed the code again by its first `verify_quote` and Open checkout shows the popup. A second tab shows no popup by itself.
- **Simulated mode.** There is no Paystack, so there is no popup: the simulator's checkout page stays the redirect path, its access code is never handed out, and the approval card declares no origin (the public deployment is like this, so no visitor sees the line).
- **Switch.** `INLINE_PAYSTACK` (host and connectors; default on). Off: the host refuses Paystack's origins, does not list them, and the connector neither declares them nor hands out a code.

**What Paystack's popup needs** (observed against a real test transaction, `inline-checkout-real.mjs`): the card asked `js.paystack.co` once (the script) and `checkout.paystack.com` four times (the frame). Inside the popup, Paystack's own page reached `api.paystack.co`, `checkout.paystack.com`, `www.googletagmanager.com`, `fonts.googleapis.com`, `eu-assets.i.posthog.com` and two Amazon S3 hosts; those are inside Paystack's frame, under its own policy, not ours. No policy violation was reported with the two origins declared. No `connectDomains` are needed.

Verified: the popup **loads** (script, frame, `onLoad`, the checkout for "Pay NGN 2,500" on screen) in Chromium behind the proxy, against Paystack's real test mode, with nothing typed and nothing paid (`docs/screens/inline-popup-real.png`); the same declaration also loads in WebKit (exploration, not kept in the suite). **Not verified:** a payment completed in the popup, 3-D Secure, the popup's behaviour on a phone, wallet payments (no `payment` permission is delegated).

## What could not be verified

- **Claude Desktop, ChatGPT, VS Code (Copilot) and other MCP Apps hosts.** None was run. What they send in `ui/initialize`, whether they honour `visibility`, `_meta.ui.csp`, `domain`, `prefersBorder`, whether they speak the stateless era, and how they draw a card are unknown. The card follows the standard and falls back to `ui/open-link` when the host does not declare what the popup needs. The connectors answer both eras of MCP and the official clients pinned to each.
- **iOS Safari** and any real phone: the proxy suite ran in Chromium and WebKit (Playwright's), which is not Safari on iOS. `env(safe-area-inset-*)` is 0 in Chromium.
- **Firefox.**
- **A completed payment through the popup, 3-D Secure**, and everything after the popup loads.
- **The sandbox Worker on Cloudflare**: it was not deployed. Its response headers are checked in Node and in workerd (the local stack); the smoke test in `tools/deploy.sh` is written, not run.
- Requests from a browser to the connectors (`MCP_ALLOWED_ORIGINS`) have no client in the suites beyond a unit test.
- Screen readers: the domains line is tied to the frame with `aria-describedby`; nothing was read out.

## How each check is run

```
node --test sandbox/test/*.test.mjs                       # the policy builder and validator, the Worker's headers
cd host && uv run pytest tests/test_card_csp.py           # validation, allowlist, permissions, the JSON the page gets
cd checkout && uv run pytest tests/test_mcp_modern.py tests/test_inline_checkout.py
tools/up.sh                                               # then, with PORT_BASE set:
node conformance/chat-bridge.mjs                          # order, initialize result, context changes, display modes, teardown
PAYSTACK_RIG=fake tools/up.sh                             # a stack whose paystack-pay connector is in Paystack test mode
node conformance/sandbox-proxy.mjs                        # the proxy (ENGINE=webkit for WebKit); needs base+3 and base+7 free
node conformance/inline-checkout.mjs                      # the popup, every fallback, the allowlist end to end
node conformance/inline-checkout-hosts.mjs                # hosts without the capability, without full screen, that refuse it
PAYSTACK_RIG=real tools/up.sh && node conformance/inline-checkout-real.mjs   # the one run against Paystack's test mode
```

`tools/check.sh` runs all but the last. `PAYSTACK_RIG=real` starts `conformance/paystack-rig.mjs` in forwarding mode: it alone reads the `sk_test_` key from the untracked `.env.local` at the repository root, refuses any other key, and prints neither the key nor a code nor a link.
