# Third-party notices

234 is licensed under the GNU AGPL v3 or later ([LICENSE](LICENSE), [NOTICE](NOTICE)). The components below keep their
own licences. The licence of each was read from its package metadata (npm `license` field in `package-lock.json`,
Python distribution metadata of the locked versions) or from the licence file shipped beside the vendored copy.

## Copied into the repository

| Component | Version | Licence | Where | Source |
|---|---|---|---|---|
| markdown-it | 15.0.2 | MIT | `host/src/chat/static/chat/vendor/markdown-it.esm.min.mjs`, licence in `markdown-it.LICENSE` | https://github.com/markdown-it/markdown-it |
| Firebase JS SDK (`firebase/app`, `firebase/auth`, bundled by `tools/vendor-firebase.sh`) | 12.19.0 | Apache-2.0 | `host/src/chat/static/chat/vendor/firebase-auth.esm.min.js`, licence text in `firebase-auth.LICENSE.txt` | https://github.com/firebase/firebase-js-sdk |
| idb (inside the Firebase bundle) | 7.1.1 | ISC | same file | https://github.com/jakearchibald/idb |
| tslib (inside the Firebase bundle) | 2.8.1 | 0BSD | same file | https://github.com/Microsoft/tslib |
| Manrope (Latin subset, weight axis 500 to 800) | | SIL OFL 1.1 | `host/src/chat/static/chat/fonts/manrope.woff2`, licence in `OFL.txt` | https://github.com/sharanda/manrope |
| Google "G" logo | | Trademark of Google LLC, used under Google's branding guidelines for sign-in buttons | `host/src/chat/static/chat/brand/google-g.svg` | https://developers.google.com/identity/branding-guidelines |
| Built card of the TypeScript original: React, react-dom, scheduler, zod and `@modelcontextprotocol/ext-apps` inside one minified HTML file | React 19.3.0, zod 4.6.5, ext-apps 2.0.3 | MIT | `checkout/src/checkout/card/react-card.html` (a comparison fixture, served only as an alternative card in development) | https://github.com/facebook/react, https://github.com/colinhacks/zod, https://github.com/modelcontextprotocol/ext-apps |

Notes:

- The markdown-it browser build inlines mdurl, uc.micro, linkify-it and punycode.js (MIT) and entities
  (BSD-2-Clause). The notice file beside it carries markdown-it's own licence only.
- Manrope is used unmodified in form (subset only). The OFL allows bundling and use with software under another
  licence; the font is not sold on its own.
- `react-card.html` is a minified build: the notices of the libraries inside it are not in the file. All of them are
  MIT, which requires the notice to travel with copies. This is listed as an open item (below).

## Bundled into built files that a deployment serves

| Component | Version | Licence | Used in |
|---|---|---|---|
| `@modelcontextprotocol/ext-apps` (AppBridge and App client) and, inside it, `@modelcontextprotocol/client`, `@modelcontextprotocol/core`, zod, jose, eventsource, eventsource-parser, pkce-challenge, cross-spawn, which, isexe, path-key, shebang-command, shebang-regex, `@standard-schema/spec` | 2.0.3 (client and core 2.2.0, zod 4.6.5) | MIT (isexe and which: ISC) | `host/build/app-bridge.min.js` and the official-client card, both built by `npm run build:host` and `card/build.py` and not committed |

## Python, deployed in the Workers

| Package | Licence | Project |
|---|---|---|
| Django 6.1 | BSD-3-Clause | host |
| asgiref, sqlparse | BSD-3-Clause | host |
| django-cf | MIT | host |
| httpx, httpcore | BSD-3-Clause | host |
| anyio, h11 | MIT | host |
| idna | BSD-3-Clause | host |
| certifi | MPL-2.0 | host |
| typing-extensions | PSF-2.0 | host, connectors |
| tzdata | Apache-2.0 | host |
| workers-runtime-sdk | MIT | host |
| pydantic, pydantic-core, annotated-types, typing-inspection | MIT | connectors |

## Development and test tools (not distributed)

Node (`package.json`): `@a2a-js/sdk` (Apache-2.0), `@modelcontextprotocol/client` (MIT), `@modelcontextprotocol/ext-apps`
(MIT), `@tailwindcss/cli` and `tailwindcss` 4.3 (MIT), `esbuild` (MIT), `playwright` (Apache-2.0), `typescript`
(Apache-2.0), `wrangler` (MIT OR Apache-2.0). Their dependency trees in `package-lock.json` are MIT, ISC,
Apache-2.0, BSD and 0BSD, with three groups worth naming: the optional `@img/sharp-*` native libraries that come with
wrangler (LGPL-3.0-or-later, Apache-2.0), `lightningcss` (MPL-2.0, used by Tailwind's build) and `@speed-highlight/core`
(CC0-1.0). None is copied into this repository or into a built file.

Python (dependency groups): pytest, pytest-asyncio (Apache-2.0), pytest-django (BSD-3-Clause), ruff (MIT), websockets
(BSD-3-Clause), cryptography (Apache-2.0 OR BSD-3-Clause), workers-py (MIT), mcp (MIT), `a2a-sdk` (Apache-2.0).

Also used when a developer runs the full check, never copied here: `firebase-tools` through `npx` (the Auth emulator),
and Chromium, WebKit and Firefox through Playwright.

Paystack's `inline.js` is loaded by a visitor's browser from Paystack when a card pays in Paystack's popup; it is not
distributed here.

## Compatibility with the AGPL-3.0-or-later

- MIT, ISC, BSD-2-Clause, BSD-3-Clause, 0BSD, CC0-1.0, PSF-2.0 and SIL OFL 1.1: compatible.
- Apache-2.0: compatible with the GPL version 3 and so with the AGPL version 3 (it is not compatible with GPL
  version 2 only; this project is licensed under version 3 or later, so that does not apply).
- MPL-2.0 (certifi, lightningcss): compatible; MPL 2.0 lists the AGPL as a permitted secondary licence. certifi's
  files stay under the MPL.
- LGPL-3.0-or-later (the optional sharp libvips binaries that wrangler may install): compatible, and in any case
  a development tool dependency that is not distributed with this project.

No licence found is incompatible with the AGPL-3.0-or-later.

## Open items

1. **Notices inside minified files.** `react-card.html` and markdown-it's browser build inline MIT and BSD-2-Clause code
   whose notices are not in the file beside them. Either add the notices here in full, or rebuild the files with
   licence comments kept (esbuild `--legal-comments=eof`).
2. **`react-card.html`** exists only to compare the Python card with the TypeScript original. If that comparison is
   no longer needed, remove the file, `ALT_CARDS=react=...` in `tools/up.sh` and the `react` entry in
   `conformance/card-states.mjs`.
3. **The concept art** the brand was traced from (AI-generated images) is not distributed; the traced vector assets
   are this project's brand assets ([TRADEMARKS.md](TRADEMARKS.md)).
4. **The Google "G"** is Google's mark: check the current branding guidelines before changing the sign-in button.
