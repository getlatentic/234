# Sign in with Google

Optional, and off until configured. A person can keep using the site as a visitor, exactly as before. Signing in (Google accounts only, through Firebase Auth; no phone, no SMS, no password) gives them the same chats and the same daily allowance on every device.

All numbers and runs here are local: workerd, local D1, the Firebase Auth **emulator** and a stand-in for Google's key document. Nothing was deployed and no real Firebase or Google service was used for anything but one static script (see "What was and was not verified").

## The design

- **Where.** Only in the chats drawer. A "Continue with Google" button (Google's own: its G mark and its neutral light and dark surface, edge and label colours, in `design/tokens.json` as `google-*`), and after sign-in the account (email, a small avatar initial) and "Sign out". No header button, no modal, no extra copy. The chats button is shown on the empty home when sign-in is on, because the drawer is the only place to sign in.
- **Client.** The Firebase JS SDK 12.19.0, modular, bundled into one 112 KB file (`static/chat/vendor/firebase-auth.esm.min.js`, made by `tools/vendor-firebase.sh`, Apache-2.0, `firebase-auth.LICENSE.txt` beside it; the SDK's `idb` is ISC and `tslib` 0BSD). It is fetched by `import()` when the person presses the button, or when a sign-in that went through a redirect comes back; the home loads none of it (`conformance/chat-auth.mjs` checks the request log). It uses `signInWithPopup` with `GoogleAuthProvider`; if the browser blocks the popup it says "Opening Google in this tab." and uses `signInWithRedirect`. The SDK keeps its user in memory only (`inMemoryPersistence`) and is signed out the moment our session is set: no ID token or Firebase user is stored in the browser.
- **Exchange.** The page posts the ID token to `POST /auth/session` (CSRF protected like every other POST, rate limited to the chat limiter's 12 a minute per client address). The server verifies it (below), derives the owner, moves the anonymous visitor's chats to it and sets **our own** session cookie. `POST /auth/signout` clears it. Both answer 404 when sign-in is off.
- **Identity.** A signed-in person's owner is `u:` and 32 hex characters of `HMAC-SHA256(ACCOUNT_KEY, "account-owner:" + uid)`. The connectors' owner rule (32 hex, scoped per owner) and the per-owner daily allowance therefore apply unchanged, and the same uid on two devices is one owner with one set of chats and one allowance. The same key is the owner of the account's saved notes ([memory.md](memory.md)), which only a signed-in account has. An anonymous visitor keeps the cookie-derived id. `ACCOUNT_KEY` is a key of its own (a generated secret, never rotated by `tools/deploy.sh`): rotating `DJANGO_SECRET_KEY` signs everyone out, and must not orphan anyone's chats.
- **Adoption.** At sign-in the current anonymous visitor's chats (and their guest passes from share links) become the account's: one `UPDATE` of the owner column, no row of any log touched, so nothing is copied, merged or lost, and an account that already has chats simply has more. It is idempotent (a sign-in that failed half-way is repeated by the next), and it runs at every sign-in, so a second device's anonymous chats join the account too. The chat's Durable Object reads its owner on every use (it used to keep it), so a live object follows the move at once.
- **Approval cards.** A quote made under the anonymous key stays bound to it. An approval card still open in an adopted chat asks the connector under the account's key, the connector does not know the quote (`QUOTE_NOT_FOUND`), and the card shows its own **"No longer available"** state (neutral, no buttons, no error text) instead of the connector's error; nothing was approved or paid. The card finds out when the person presses something or the quote expires, not at adoption. See [durable-chat.md](durable-chat.md).
- **Sign-out** deletes the session cookie and sets a fresh anonymous visitor cookie: a stranger to everything the account held. The anonymous visitor cookie is deleted at sign-in, so the account's chats are never reachable by a visitor id.
- **A2A and the sandbox** are untouched: A2A callers have their own owners (`a:<name>`), and the card sandbox's proxy and card policies are unchanged.

## What the server verifies in an ID token

`accounts/firebase_token.py`, about 100 lines, tested in `host/tests/test_firebase_token.py` with RSA keys generated in the test (signed by the `cryptography` package, a dev-only dependency, so one implementation signs and the other judges):

1. Size at most 8 KB, three dot-separated base64url parts, JSON header and payload.
2. **RS256 and nothing else.** `alg: none`, `HS256`, `RS384`, `ES256`, `PS256`, a lowercase `rs256` and an empty one are refused before any key is looked at.
3. The `kid` names one of Google's current keys; the signature verifies against that key (`accounts/rs256.py`: one `pow`, and the PKCS#1 padding is rebuilt and compared whole, so a padding with garbage in it is refused; keys under 2048 bits, even or huge exponents and signatures of the wrong length are refused).
4. `iss` is `https://securetoken.google.com/<project>` and `aud` is the project id.
5. `exp` not past, `iat` and `auth_time` not in the future (60 seconds of skew), and a life of at most an hour (Firebase's).
6. `sub` a non-empty string, `email` present, `email_verified` exactly `true`, `firebase.sign_in_provider` exactly `google.com`.

Keys (`accounts/keys.py`): fetched from Google's published key document, cached for as long as its `Cache-Control: max-age` says (clamped to 1 minute to a day). A token naming an unknown `kid` makes one refetch, and never more than one a minute, so random `kid`s cannot become a stream of requests to Google. A fetch that fails is a 503, not a sign-in.

**Why the JWK form, not the x509 one.** Firebase's documentation names `.../robot/v1/metadata/x509/securetoken@system.gserviceaccount.com`. The same keys, with the same `kid`s, are published in JSON Web Key form at `.../robot/v1/metadata/jwk/securetoken@system.gserviceaccount.com` (the modulus and the exponent, ready to use), which saves parsing a certificate in DER with hand-written code. Nothing is lost: the certificate's validity dates are not a check Firebase asks of a verifier.

**Why not `cryptography`, and the alternative.** The host's startup snapshot is 12.1 MB gzip of a cap near 19.7 MB, and `cryptography` would add tens of megabytes. A common way to avoid it is to send every ID token to Identity Toolkit (`accounts:lookup` with the project's web API key), which checks the signature and expiry, then compares the decoded claims with the project. That costs one network call to Google per sign-in and needs the API key on the server. Here the signature is checked in this process with `pow` and `hashlib` (the snapshot does not change: measured below), the API key stays a public identifier only the page needs, and the only request to Google is the key document, once an hour.

**Not checked:** that the account has not been disabled or deleted at Google since the token was issued (a token is good for up to an hour, and our session for 30 days once made; the session is not re-verified against Firebase); the token's `nonce`; revocation. See the threat model.

## The session cookie

`session` (`accounts/session.py`): HttpOnly, Secure outside development, SameSite=Lax, host-only (no `Domain`), 30 days, path `/`. It is a new value at every sign-in (a random nonce is inside it). It holds the owner key, the email (to draw the drawer) and the nonce, signed with Django's signer (salted `accounts.session`) and checked for age on every read; it is not encrypted, it never holds the ID token, and a script cannot read it. It cannot be revoked one at a time: signing out deletes it in that browser, and a new `DJANGO_SECRET_KEY` ends every session (and every visitor cookie). If a cookie is stolen it is good for up to 30 days.

## Threat model

| Attack | What stops it |
|---|---|
| A forged token (`alg: none`, HMAC with the public key as secret, a changed payload, a signature by another key with Google's `kid`) | RS256 only, the padded digest rebuilt and compared, the key from Google's document by `kid` (tests for each) |
| A valid token of another Firebase project or another provider (a Facebook or phone sign-in of our own project) | `iss`, `aud`, `sign_in_provider == google.com`, `email_verified` |
| A replayed old token | `exp` with 60 s of skew and a one-hour life; the replay of a live token yields the same session its owner already has (no new capability) |
| Login CSRF (making a victim's browser sign in as the attacker) | `POST /auth/session` needs Django's CSRF token, which a foreign site cannot read; SameSite=Lax cookies |
| Hammering the endpoint, or unknown `kid`s to make us hammer Google | the chat limiter per client address; one key refetch a minute |
| Session theft by script | HttpOnly; the page's policy allows scripts only from itself and `apis.google.com` |
| A public site accepting the emulator's unsigned tokens | `FIREBASE_AUTH_EMULATOR_HOST` and `FIREBASE_KEYS_URL` stop the host at startup unless `DJANGO_DEBUG` is on, and with `REQUIRE_OWNER=1` even then; without the host setting the verifier refuses `alg: none`. The public template sets neither (tested, including a subprocess that loads the public configuration with sign-in on and offers it an unsigned token) |
| One person reading another's chats | chats are scoped by owner (the owner is an HMAC of the uid under a secret key); another account, and the visitor a sign-out returns to, get 404 (tests) |
| An attacker who can read the database learning uids | the owner is an HMAC under `ACCOUNT_KEY`; the database holds no uid and no ID token |
| Losing everyone's chats | `ACCOUNT_KEY` is generated once by the deploy and never rotated by it; rotating `DJANGO_SECRET_KEY` only signs people out |
| A disabled Google account still signed in | **Not stopped** for up to 30 days (sessions are not re-checked). Acceptable for simulated money; a deployment that moves real money must re-verify, or shorten the session |

## Policy and opener: what sign-in adds

Only when sign-in is on, `chat/security.py` adds exactly this to the page policy, and `settings.py` changes the opener policy:

| Directive | Added | Why |
|---|---|---|
| `script-src` | `https://apis.google.com` | the SDK loads Google's iframe API (`/js/api.js`) for its popup and redirect flows; observed requested even against the emulator |
| `connect-src` | `https://identitytoolkit.googleapis.com`, `https://securetoken.googleapis.com`, `https://apis.google.com`, `https://www.google.com/images/cleardot.gif` | the two API hosts the SDK calls (found as strings in the vendored bundle); the script's beacons: `apis.google.com/js/gen_204` and, in some runs, one pixel of `www.google.com` (named by its path, not the host). Each was refused at first and raised a console error in a run of the emulator suite, so each is listed: they were found by running, and a run of real Google may find another |
| `frame-src` | `https://<FIREBASE_AUTH_DOMAIN>` | the SDK's hidden handler iframe (`/__/auth/iframe`) |
| `Cross-Origin-Opener-Policy` | `same-origin-allow-popups` (instead of Django's default `same-origin`) | the popup has to keep its link to the page; measured: the emulator's window finds its opener and relays the result through the iframe |

`style-src`, `img-src` (the G mark is a same-origin file), `form-action`, `frame-ancestors` and the sandbox's frame-src are unchanged, and the card sandbox's and the cards' policies are not touched. Against the emulator the list also has the emulator's origin in `connect-src` and `frame-src`, and only when `FIREBASE_AUTH_EMULATOR_HOST` is set. `conformance/chat-auth.mjs` runs the whole flow under this policy with no policy violation or page error.

**Derived, not observed, for the real Google:** `https://<authDomain>` as the frame (the emulator's iframe is on its own origin), any further gapi script the real `api.js` loads from `apis.google.com` (the run saw its `gapi_iframes` module from that host), and whether the real Google sign-in page's own opener policy lets the handler reach the page. Run one real sign-in and read the console for policy violations before trusting this list.

## Configuration

| Name | Public? | Where | What |
|---|---|---|---|
| `FIREBASE_PROJECT_ID` | yes | Worker variable, from `.env.auth.local` | your Firebase project's id (`<your-firebase-project-id>`) |
| `FIREBASE_API_KEY` | yes (an identifier, not a secret) | Worker variable, from `.env.auth.local` | the web app's `apiKey` |
| `FIREBASE_AUTH_DOMAIN` | yes | Worker variable, from `.env.auth.local` | the web app's `authDomain` (`<your-firebase-project-id>.firebaseapp.com`) |
| `ACCOUNT_KEY` | **secret** | Worker secret, generated by `tools/deploy.sh` once, kept after | the key of the owner derivation |
| `FIREBASE_AUTH_EMULATOR_HOST`, `FIREBASE_KEYS_URL` | development only | local stack only | the emulator and a stand-in for Google's keys; refused outside `DJANGO_DEBUG` |

Sign-in is on only when all four of the first four are set: without them the page has no button, `/auth/session` and `/auth/signout` answer 404, the opener policy is `same-origin`, and the policy has none of the additions above. The format of `.env.auth.local` and what `tools/deploy.sh` does with it are in [deploy.md](deploy.md).

## What you do in the console

The repository never touches the Firebase console. For your Firebase project (Spark plan: Google sign-in is free and there is no SMS):

1. Authentication, Sign-in method: enable **Google** (set its public name and a support email) and no other provider. Phone stays off.
2. Project settings, Your apps: add a **Web app**; copy its `apiKey`, `authDomain` (normally `<your-firebase-project-id>.firebaseapp.com`) and `projectId` into `.env.auth.local` ([deploy.md](deploy.md#sign-in-with-google-optional-off-until-the-file-exists)).
3. Authentication, Settings, **Authorized domains:** add `<host-worker>.<your-subdomain>.workers.dev` (the host Worker's address; `localhost` and the `firebaseapp.com` domain are there already).
4. Optional: in Google Cloud, Credentials, restrict the web app's API key to the HTTP referrer `https://<host-worker>.<your-subdomain>.workers.dev/*` and to the Identity Toolkit API (the key is public either way).
5. `tools/deploy.sh auth` (names only) and then `tools/deploy.sh`; its smoke test says whether sign-in came up.
6. Sign in once with a real Google account, with the browser's console open, on a desktop and on a phone, and report any line about a policy violation, a blocked popup or an opener: the real-Google entries of the policy list above are derived, not observed.

## Local runs

`AUTH=1 PORT_BASE=8920 tools/up.sh` starts the stack with sign-in on against the Firebase Auth emulator (`firebase-tools` 15.32.0 through `npx`, pinned in `tools/stack.sh`; Auth needs no Java, no login and no install in the repository; demo project `demo-twothreefour`; its ports are base+7 to base+9) and `conformance/fake-google-keys.mjs` (base+17: an RSA key pair, its public half served as Google's document with a one-hour `max-age`, the private half in `.stack/<base>/keys/` for the suite that signs tokens). `AUTH=keys` starts the stack the way public is configured: sign-in on, the stand-in for Google's keys, and no emulator, so an unsigned token is refused. `tools/down.sh` stops them.

## Evidence

| Run | What it holds |
|---|---|
| `host/tests/test_firebase_token.py` (42) | valid; wrong `aud`; wrong `iss`; expired (and accepted inside the skew); not yet valid; `alg: none` and seven other algorithms; an HMAC token; tampered signature and payload; another key with the same `kid`; short, empty and padded signatures; unknown `kid` (one refetch, never a stream); rotated key found; `max-age` honoured; unverified email (four ways); wrong provider; no `sub`; non-numeric times; nine non-tokens; the emulator flag accepting unsigned tokens only when asked and never weakening signed ones |
| `host/tests/test_accounts.py` (23) | the owner derivation; no button without configuration; the drawer's markup; the cookie (attributes, no ID token, new at every sign-in, secure outside development); 401 for garbage and wrong tokens; CSRF; the rate limit; the emulator refused unless configured; keys unreachable is 503; a tampered or expired cookie is anonymous; adoption; two devices, one owner; another account sees none; guest passes; sign-out; the policy additions and their absence |
| `host/tests/test_auth_config.py` (10) | the public template sets no development value and no account key; development-only settings stop the host outside development and with `REQUIRE_OWNER=1`; the public configuration refuses an emulator token with sign-in on; host names are validated (they go into a policy); the four values; the opener policy; the template's marker |
| `host/tests/test_chat_core.py` | a chat moved to an account while its object is alive is spent for by the new owner |
| `host/tests/test_worker_auth.py` (7; `pytest -m worker`, against `AUTH=1` and again against `AUTH=keys`) | real RS256 through workerd and D1: the anonymous chat adopted, a second device, sign-out, another account, the chat's Durable Object spending for the account after the move (the anonymous quote is refused as unknown), eight kinds of refused token, an unsigned emulator token accepted with the emulator configured and refused without it, the limit of twelve a minute per address, CSRF |
| `conformance/chat-auth.mjs` (stack with `AUTH=1`) | no Firebase request before the press; exactly one sign-in button, in the drawer; the policy and the opener policy as served; Google's button colours, G mark and words, 44px, in both themes; sign in through the emulator's popup; the drawer reopens with the email and an initial; cookie attributes; no ID token stored; the anonymous chat adopted and opening; reload keeps the session; sign-out, fresh visitor, 404 for the account's chat; second device, same chats; another account sees none; an open approval card becomes "No longer available"; the popup-blocked redirect and its line; a refusal's line; a closed popup says nothing; real RS256 through workerd (valid accepted; changed signature, HS256, another key under the same `kid`, garbage refused; Google's document fetched at most once for five sign-ins); 320px with a long address; contrast of the drawer; keyboard; no page error or policy violation in any run |
| `conformance/card-states.mjs checks` | the card's "No longer available" state after a `QUOTE_NOT_FOUND`, for a transfer and an airtime card |

Screenshots: `docs/screens/auth-drawer-signed-out-{light,dark}.png`, `auth-drawer-signed-in-{light,dark}.png` (390px), `auth-drawer-signed-in-{light,dark}-320.png`, `auth-adopted-card-no-longer-available.png`, `card-transfer-gone-{light,dark}.png`.

## Startup snapshot

`tools/snapshot-size.sh host` (the snapshot's raw and gzip bytes, and the first request after a fresh start), on the commit before this work and on the one after it, the same laptop:

| | raw | gzip | first request | next |
|---|---|---|---|---|
| before | 45,366,000 | 12,141,450 | 0.69 s | 0.41 s |
| after | 45,366,000 | 12,175,777 | 0.81 s | 0.46 s |

The gzip grew by 34,327 bytes (0.28%): the `accounts` modules. The cap is near 19.7 MB, so the host is at 12.18 MB of it. The raw figure did not move.

## What was and was not verified

- **Verified locally:** everything in the evidence table, on Chromium, against the emulator.
- **One request to a real Google host:** the SDK loads `https://apis.google.com/js/api.js` (and, from it, the `gapi_iframes` module) even against the emulator. It is a static script, no project or account is involved, and the suite needs the network for it. The emulator's own popup page asks for `unpkg.com` and Google Fonts; the suite refuses those at name resolution (a request interceptor is not an option: Chromium's local-network checks then block the emulator's iframe).
- **Not verified:** real Google and Firebase (the real popup, the consent screen, a real ID token signed by Google's keys, the real `authDomain` handler, real `Cache-Control` on the key document, the project's settings), real phones, iOS Safari (its popup rules are the likeliest reason for the redirect fallback, which the suite exercises only by making `window.open` return nothing), other browsers, and the policy list's real-Google entries above.
