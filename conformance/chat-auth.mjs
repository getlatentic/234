// SPDX-License-Identifier: AGPL-3.0-or-later
// Sign in with Google, in a real browser against the Firebase Auth emulator and a stand-in for Google's keys
// (the stack started with AUTH=1: docs/auth.md). The emulator's own "Google" popup is used as a person uses
// Google's. Not faked: the vendored Firebase SDK, the page's policy (CSP and COOP), the popup, the redirect
// fallback, our session cookie, the adoption of an anonymous visitor's chats, two devices, and sign-out.
// The one request to a real Google host is the SDK's own script, https://apis.google.com/js/api.js (static, no
// project or account): the SDK loads it even against the emulator. Requests to unpkg.com and Google Fonts that
// the emulator's popup page makes are refused at name resolution.
//
// needs the stack with AUTH=1. usage: PORT_BASE=8920 node conformance/chat-auth.mjs
import { createSign, randomBytes } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import { chromium } from "playwright";
import { contrastReport } from "./card-checks.mjs";
import { HOST, cardIn, freshLedger, suite, tokenColor, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Sign in with Google");
const base = Number(process.env.PORT_BASE ?? 8900);
const EMULATOR = `127.0.0.1:${base + 7}`;
const KEYS = `http://127.0.0.1:${base + 17}`;
const KEY_DIR = new URL(`../.stack/${base}/keys/`, import.meta.url).pathname;
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
await freshLedger();

const browser = await chromium.launch({
  args: ["--host-resolver-rules=MAP fonts.googleapis.com ~NOTFOUND, MAP fonts.gstatic.com ~NOTFOUND, MAP unpkg.com ~NOTFOUND"],
});
const errors = [];
const warnings = [];
const run = randomBytes(3).toString("hex");
const emailOf = (who) => `${who}.${run}@example.com`;

async function device(options = {}, watch = true) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, ...options });
  const page = await context.newPage();
  if (watch) watchErrors(page, errors);
  page.on("console", (m) => m.type() === "warning" && m.text().startsWith("sign-in:") && warnings.push(m.text()));
  await page.goto(`${HOST}/`);
  return { context, page };
}

const drawer = (page) => page.locator("chat-sheet dialog");
const atRest = async (page) => {
  await drawer(page).waitFor({ state: "visible" });
  await drawer(page).evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)));
  await page.waitForTimeout(60);
};
async function openChats(page) {
  await page.getByRole("button", { name: "Chats" }).click();
  await atRest(page);
}

/** What a person does in the emulator's "Google" window: pick the account if it exists, else add it. */
async function chooseAccount(where, email) {
  await where.locator("#accounts-list").waitFor({ state: "visible", timeout: 15000 });
  const existing = where.locator("li.js-reuse-account", { hasText: email });
  if (await existing.count()) return existing.click();
  await where.locator("#add-account-button button").click();
  await where.locator("#email-input").fill(email);
  await where.locator("#sign-in").click();
}

// Sign-ins are limited to 12 a minute for one address and each takes seconds to reach the server, so the suite spends at most 6 in any minute of its own.
const spent = [];
async function pace() {
  while (spent.filter((at) => Date.now() - at < 60000).length >= 6) await new Promise((done) => setTimeout(done, 1000));
  spent.push(Date.now());
}

const signedIn = (page) => page.locator('chat-account [data-slot="email"]');
async function googleSignIn(page, email) {
  if (!(await drawer(page).isVisible())) await openChats(page);
  await pace();
  const popup = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Continue with Google" }).click();
  const window = await popup;
  await chooseAccount(window, email);
  await becomesSignedIn(page, window);
}

/** Waits for the signed-in drawer; when it does not come, says where the sign-in stopped. */
async function becomesSignedIn(page, window = null) {
  await signedIn(page).waitFor({ timeout: 25000 }).catch(async (problem) => {
    const state = {
      url: page.url().slice(0, 90), drawer: await drawer(page).isVisible().catch(() => "?"),
      popupClosed: window ? window.isClosed() : "none", popupText: window && !window.isClosed() ? (await window.locator("body").innerText().catch(() => "?")).slice(0, 160) : "",
      session: Boolean(await cookieOf(page.context(), "session")), emailInDom: await page.locator('chat-account [data-slot="email"]').count().catch(() => "?"),
      note: await page.locator('chat-account [data-slot="note"]').innerText().catch(() => "?"),
      pending: await page.evaluate(() => JSON.stringify({ ...sessionStorage })).catch(() => "?"),
    };
    throw new Error(`sign-in did not finish: ${JSON.stringify(state)} ${errors.slice(-3)} ${warnings.slice(-3)}`, { cause: problem });
  });
}

const cookieOf = async (context, name) => (await context.cookies()).find((c) => c.name === name);
const post = async (context, page, path, body) => {
  await pace();
  return page.evaluate(
    async ({ path, body }) => {
      const token = document.querySelector('meta[name="csrf-token"]').content;
      const r = await fetch(path, { method: "POST", headers: { "content-type": "application/json", "X-CSRFToken": token }, body: JSON.stringify(body) });
      return { status: r.status, body: await r.json().catch(() => ({})) };
    },
    { path, body },
  );
};
const chatIds = (page) => page.locator('chat-sheet [data-slot="rows"] a[data-slot="open"]').evaluateAll((links) => links.map((a) => a.getAttribute("href").split("/")[2]));

console.log("nothing about Firebase loads until the button is pressed");
{
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const requested = [];
  page.on("request", (r) => requested.push(r.url()));
  watchErrors(page, errors);
  await page.goto(`${HOST}/`);
  await page.waitForLoadState("networkidle");
  const foreign = requested.filter((url) => !url.startsWith(HOST));
  check(foreign.length === 0, `the home makes no request beyond its own origin (${foreign.length})`);
  check(!requested.some((url) => /firebase|gapi|apis\.google/.test(url)), "no Firebase file, no Google script, before the press");
  const sdk = await page.evaluate(() => performance.getEntriesByType("resource").filter((e) => /vendor\/firebase/.test(e.name)).length);
  check(sdk === 0, "the vendored SDK (112 KB) is not fetched with the page");
  check((await page.locator('[data-action="chats"]').isVisible()) && (await page.locator("[data-action=sign-in]").count()) === 1, "the chats button is there for a visitor with no chats, and the page has exactly one sign-in button");
  check((await page.locator('dialog button:has-text("Continue with Google")').count()) === 1, "and it is inside the chats drawer");
  check((await page.locator("header, footer, nav, [role=banner]").count()) === 0, "there is still no header, footer or bar");
  const headers = (await context.request.get(`${HOST}/`)).headers();
  check(headers["cross-origin-opener-policy"] === "same-origin-allow-popups", `the page lets its popup keep its link to it (COOP ${headers["cross-origin-opener-policy"]})`);
  const csp = Object.fromEntries(headers["content-security-policy"].split("; ").map((d) => [d.split(" ")[0], d.split(" ").slice(1)]));
  check(csp["script-src"].join(" ") === "'self' https://apis.google.com", `script-src adds only apis.google.com (${csp["script-src"].join(" ")})`);
  check(csp["connect-src"].includes("https://identitytoolkit.googleapis.com") && csp["connect-src"].includes("https://securetoken.googleapis.com") && csp["connect-src"].includes(`http://${EMULATOR}`), "connect-src adds the two Firebase API hosts and apis.google.com, where the script beacons (and the emulator here)");
  check(csp["frame-src"].includes("https://localhost") && csp["frame-src"].some((s) => s.startsWith("http://127.0.0.1:")), "frame-src adds the auth domain (and the sandbox and the emulator here)");
  check(csp["style-src"].join(" ") === "'self'" && csp["img-src"].join(" ") === "'self' data:" && csp["frame-ancestors"].join(" ") === "'none'", "style-src, img-src and frame-ancestors are unchanged");
  const before = await page.evaluate(() => ({ local: Object.keys(localStorage), session: Object.keys(sessionStorage) }));
  check(before.local.length === 0, "and nothing is stored in the browser yet");
  await context.close();
}

console.log("the button is Google's: neutral, the G mark, the words it allows");
{
  for (const scheme of ["light", "dark"]) {
    const { context, page } = await device({ colorScheme: scheme });
    await openChats(page);
    const button = page.getByRole("button", { name: "Continue with Google" });
    const style = await button.evaluate((el) => {
      const s = getComputedStyle(el);
      const box = el.getBoundingClientRect();
      const img = el.querySelector("img");
      return { bg: s.backgroundColor, border: s.borderTopColor, ink: s.color, radius: s.borderTopLeftRadius, height: box.height, icon: [img.width, img.height], src: img.getAttribute("src"), loaded: img.complete && img.naturalWidth > 0, text: el.textContent.trim() };
    });
    check(style.bg === (await tokenColor(page, "google-surface")) && style.border === (await tokenColor(page, "google-edge")) && style.ink === (await tokenColor(page, "google-ink")), `${scheme}: Google's own surface, edge and label colours (${style.bg}, ${style.border}, ${style.ink})`);
    check(style.text === "Continue with Google" && style.icon[0] === 20 && style.loaded && style.src.endsWith("google-g.svg"), `${scheme}: the official G mark at 20px and "Continue with Google"`);
    check(style.height >= 44 && parseFloat(style.radius) > 20, `${scheme}: a 44px pill, not the brand green (${style.height}px)`);
    const low = await page.evaluate(`(${contrastReport.toString()})()`);
    check(low.length === 0, `${scheme}: every text in the drawer meets WCAG AA ${JSON.stringify(low)}`);
    await page.screenshot({ path: `${screens}auth-drawer-signed-out-${scheme}.png` });
    await context.close();
  }
}

console.log("anonymous use is untouched");
const anonymous = await device();
{
  await anonymous.page.locator("#text").fill("What can you do?");
  await anonymous.page.getByRole("button", { name: "Send", exact: true }).click();
  await anonymous.page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  await anonymous.page.locator("assistant-text").first().waitFor({ timeout: 20000 });
  check(true, "a visitor who never signs in starts a chat and gets an answer");
}

console.log("signing in through the popup");
const ada = emailOf("ada");
const requests = [];
anonymous.page.on("request", (r) => requests.push(r.url()));
let anonymousChat;
{
  const { page, context } = anonymous;
  anonymousChat = new URL(page.url()).pathname.split("/")[2];
  const visitorBefore = await cookieOf(context, "visitor");
  await googleSignIn(page, ada);
  const hosts = new Set(requests.map((u) => new URL(u).origin));
  const allowed = new Set([HOST, `http://${EMULATOR}`, "https://apis.google.com"]);
  check([...hosts].every((h) => allowed.has(h) || /127\.0\.0\.1:\d+$/.test(h)), `the page and its frames spoke only to its own origin, the emulator and apis.google.com (${[...hosts].join(", ")})`);
  check((await signedIn(page).innerText()) === ada && (await drawer(page).isVisible()), "the drawer reopens, signed in, and shows the email");
  check((await page.locator('chat-account [data-slot="account"] span[aria-hidden]').innerText()) === "A", "with a small avatar initial");
  check((await page.getByRole("button", { name: "Sign out" }).count()) === 1 && (await page.getByRole("button", { name: "Continue with Google" }).count()) === 0, "and Sign out; the Google button is gone");
  const session = await cookieOf(context, "session");
  check(session && session.httpOnly && session.sameSite === "Lax" && !session.domain.startsWith(".") && Math.abs(session.expires - (Date.now() / 1000 + 30 * 86400)) < 600, `our session cookie is HttpOnly, SameSite=Lax, host-only (${session?.domain}) and lasts 30 days`);
  check(!(await page.evaluate(() => document.cookie)).includes("session="), "a script cannot read it");
  check(!session.value.includes("eyJhbGci") && session.value.length < 400, "it does not hold the ID token");
  check((await cookieOf(context, "visitor")) === undefined || (await cookieOf(context, "visitor")).value !== visitorBefore.value, "the anonymous visitor cookie is gone");
  const stored = await page.evaluate(async () => ({
    local: Object.entries(localStorage).map(([k, v]) => k + v), session: Object.entries(sessionStorage).map(([k, v]) => k + v),
    idb: (await indexedDB.databases()).map((d) => d.name),
  }));
  check(![...stored.local, ...stored.session].some((v) => /eyJhbGci|firebase:authUser/.test(v)), `no ID token or Firebase user is kept in the browser (${stored.idb.join(", ") || "no databases"})`);
  check(!stored.idb.includes("firebaseLocalStorageDb"), "the SDK's own user database was never made");
  check((await chatIds(page)).includes(anonymousChat), "the chat the visitor made before signing in is in the account's list");
  await page.goto(`${HOST}/c/${anonymousChat}/`);
  check((await page.locator("assistant-text").count()) > 0, "and it opens, with its messages");
}

console.log("the session survives a reload");
{
  const { page, context } = anonymous;
  await page.goto(`${HOST}/`);
  await openChats(page);
  check((await signedIn(page).innerText()) === ada, "after a reload the drawer still shows the account");
  const rotated = (await cookieOf(context, "session")).value;
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.locator("chat-account").getByRole("button", { name: "Continue with Google" }).waitFor({ timeout: 15000 });
  check(true, "Sign out leaves the drawer offering Google again");
  check(!(await cookieOf(context, "session")), "the session cookie is deleted");
  const visitor = await cookieOf(context, "visitor");
  check(visitor && visitor.value.length > 10, "a fresh anonymous visitor cookie is set");
  check((await chatIds(page)).length === 0 && (await page.request.get(`${HOST}/c/${anonymousChat}/`)).status() === 404, "the account's chats are not visible to that visitor, and their address is a 404");
  await googleSignIn(page, ada);
  check((await chatIds(page)).includes(anonymousChat), "signing in again brings them back");
  check((await cookieOf(context, "session")).value !== rotated, "and the session is a new value");
}

console.log("a second device, the same account");
const other = await device();
{
  const { page } = other;
  const second = (await page.evaluate(() => fetch("/", { credentials: "same-origin" }).then((r) => r.status))) === 200;
  await page.locator("#text").fill("Buy ₦500 MTN airtime for 08031234567");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await page.waitForURL(/\/c/);
  const fromOther = new URL(page.url()).pathname.split("/")[2];
  await googleSignIn(page, ada);
  const ids = await chatIds(page);
  check(second && ids.includes(anonymousChat) && ids.includes(fromOther), "it sees the first device's chat and its own anonymous chat, adopted: the merge loses nothing");
  await page.goto(`${HOST}/c/${anonymousChat}/`);
  check((await page.locator("assistant-text").count()) > 0, "and opens the first device's chat");
  await anonymous.page.goto(`${HOST}/`);
  await openChats(anonymous.page);
  check((await chatIds(anonymous.page)).includes(fromOther), "the first device sees the chat the second made");
}

console.log("an approval card still open when the visitor signs in");
{
  const { page, context } = await device();
  await page.locator("#text").fill("Buy ₦500 MTN airtime for 08031234567");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  const chat = new URL(page.url()).pathname;
  const card = cardIn(page);
  await card.getByRole("button", { name: "Decline" }).waitFor({ timeout: 25000 });
  check(await card.getByRole("button", { name: "Decline" }).isVisible(), "the anonymous visitor has an approval card waiting");
  await googleSignIn(page, emailOf("carol"));
  await page.goto(`${HOST}${chat}`);
  const again = cardIn(page);
  await again.getByRole("checkbox").check({ timeout: 25000 });
  await again.getByRole("button", { name: "Approve" }).click();
  await again.getByText("No longer available").waitFor({ timeout: 15000 });
  const text = await again.locator("body").innerText();
  check(!/QUOTE_NOT_FOUND|There is no quote/.test(text) && (await again.getByRole("button").count()) === 0, "after adoption the quote is not the account's: the card says \"No longer available\", not an error, and nothing more can be pressed");
  await page.screenshot({ path: `${screens}auth-adopted-card-no-longer-available.png` });
  await context.close();
}

console.log("another account sees none of it");
{
  const grace = await device();
  await googleSignIn(grace.page, emailOf("grace"));
  check((await chatIds(grace.page)).length === 0 && (await grace.page.request.get(`${HOST}/c/${anonymousChat}/`)).status() === 404, "a different Google account has none of those chats");
  await grace.context.close();
}

console.log("the popup is blocked: one quiet line, then the redirect");
{
  const { page, context } = await device({}, false);
  await page.addInitScript(() => {
    window.open = () => null;
    addEventListener("DOMContentLoaded", () => {
      const note = document.querySelector('chat-account [data-slot="note"]');
      note && new MutationObserver(() => note.textContent && sessionStorage.setItem("said", note.textContent)).observe(note, { childList: true, characterData: true, subtree: true });
    });
  });
  await page.reload();
  await openChats(page);
  await pace();
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await page.waitForURL(/emulator\/auth\/handler/, { timeout: 15000 });
  await chooseAccount(page, emailOf("linus"));
  await becomesSignedIn(page);
  check((await page.evaluate(() => sessionStorage.getItem("said"))) === "Opening Google in this tab.", 'one quiet line said "Opening Google in this tab." before the page went to Google');
  check((await signedIn(page).innerText()) === emailOf("linus"), "the redirect comes back and the person is signed in");
  await context.close();
}

console.log("a refused sign-in says so once");
{
  const { page, context } = await device();
  await page.evaluate((path) => { window.__refuse = true; const original = window.fetch; window.fetch = (input, init) => (String(input).includes("/auth/session") ? Promise.resolve(new Response("{}", { status: 401 })) : original(input, init)); }, "/auth/session");
  await openChats(page);
  await pace();
  const popup = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await chooseAccount(await popup, emailOf("nobody"));
  await page.locator('chat-account [data-slot="note"]', { hasText: "Sign-in did not work. Try again." }).waitFor({ timeout: 25000 });
  check((await page.getByRole("button", { name: "Continue with Google" }).isEnabled()), "a refusal leaves one line and the button usable again");
  check(!(await cookieOf(context, "session")), "and no session");
  await context.close();
}

console.log("a closed popup is not an error");
{
  const { page, context } = await device();
  await openChats(page);
  const popup = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await (await popup).close();
  await page.getByRole("button", { name: "Continue with Google" }).and(page.locator(":enabled")).waitFor({ timeout: 25000 });
  check((await page.locator('chat-account [data-slot="note"]').innerText()) === "", "closing the window says nothing and the button is usable again once the SDK has noticed");
  await context.close();
}

console.log("the server checks the signature with Google's published keys (through workerd, not the emulator)");
{
  const { page, context } = await device({}, false); // its refusals are 401s the browser logs as errors
  const pem = readFileSync(`${KEY_DIR}private.pem`, "utf8");
  const kid = readFileSync(`${KEY_DIR}kid`, "utf8").trim();
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const now = Math.floor(Date.now() / 1000);
  const claims = { iss: "https://securetoken.google.com/demo-twothreefour", aud: "demo-twothreefour", sub: `uid-${run}`, email: emailOf("signed"), email_verified: true, auth_time: now, iat: now, exp: now + 3600, firebase: { sign_in_provider: "google.com" } };
  const make = (alg, key = pem) => {
    const input = `${b64({ alg, typ: "JWT", kid })}.${b64(claims)}`;
    return `${input}.${createSign("RSA-SHA256").update(input).sign(key, "base64url")}`;
  };
  const served = async () => Number(await (await fetch(`${KEYS}/served`)).text());
  const before = await served();
  const good = await post(context, page, "/auth/session", { idToken: make("RS256") });
  check(good.status === 200 && good.body.email === emailOf("signed"), "a token signed with the published key is accepted");
  const tampered = make("RS256").replace(/(\.[A-Za-z0-9_-]{30})(.)/g, (whole, head, c) => (whole.startsWith(".eyJ") ? whole : head + (c === "A" ? "B" : "A")));
  check((await post(context, page, "/auth/session", { idToken: tampered })).status === 401, "a token with a changed signature is refused");
  check((await post(context, page, "/auth/session", { idToken: make("HS256") })).status === 401, "an HS256 token is refused");
  const wrongKey = (await import("node:crypto")).generateKeyPairSync("rsa", { modulusLength: 2048 }).privateKey.export({ type: "pkcs8", format: "pem" });
  check((await post(context, page, "/auth/session", { idToken: make("RS256", wrongKey) })).status === 401, "a token signed by another key under the same kid is refused");
  check((await post(context, page, "/auth/session", { idToken: "garbage" })).status === 401, "garbage is 401");
  const used = (await served()) - before;
  check(used <= 1, `Google's keys were fetched ${used} time(s) for five sign-ins: the cache honours max-age`);
  await context.close();
}

console.log("the same sign-in in both colours, on a 320px phone, with a long address");
for (const scheme of ["light", "dark"]) {
  const { context, page } = await device({ colorScheme: scheme, viewport: { width: 320, height: 640 } });
  await googleSignIn(page, `a.very.long.address.for.a.narrow.phone.${run}@example.com`);
  const box = await page.locator('chat-account [data-slot="email"]').evaluate((el) => ({ clipped: el.scrollWidth > el.clientWidth, overflow: document.documentElement.scrollWidth > innerWidth }));
  check(box.clipped && !box.overflow, `${scheme}: a long email is cut with an ellipsis and nothing scrolls sideways at 320px`);
  const targets = await page.locator("chat-account button").evaluateAll((bs) => bs.map((b) => b.getBoundingClientRect().height));
  check(targets.every((h) => h >= 44), `${scheme}: Sign out is a 44px target`);
  const low = await page.evaluate(`(${contrastReport.toString()})()`);
  check(low.length === 0, `${scheme}: the signed-in drawer meets WCAG AA ${JSON.stringify(low)}`);
  await atRest(page);
  await page.screenshot({ path: `${screens}auth-drawer-signed-in-${scheme}-320.png` });
  await context.close();
}
for (const scheme of ["light", "dark"]) {
  const { context, page } = await device({ colorScheme: scheme });
  await googleSignIn(page, ada);
  await atRest(page);
  await page.screenshot({ path: `${screens}auth-drawer-signed-in-${scheme}.png` });
  await context.close();
}

console.log("keyboard");
{
  const { context, page } = await device();
  await openChats(page);
  for (let i = 0; i < 8 && (await page.evaluate(() => document.activeElement?.textContent.trim())) !== "Continue with Google"; i += 1) await page.keyboard.press("Tab");
  check((await page.evaluate(() => document.activeElement?.textContent.trim())) === "Continue with Google", "Tab reaches the Google button inside the drawer");
  const ring = await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle);
  check(ring !== "none", "with a focus ring");
  await context.close();
}

check(errors.length === 0, `no page errors, no policy violations in any run (${JSON.stringify(errors.slice(0, 3))})`);
await browser.close();
finish();
