// SPDX-License-Identifier: AGPL-3.0-or-later
// The empty home is a static page that the platform serves without the Worker (docs/performance.md): it is
// the same for everyone, and /api/me gives the page what is the visitor's (CSRF token, chats, account). In a real
// browser this checks: the page's headers; that it renders and takes typing while /api/me is held back for three
// seconds; that a first message sent before the token has arrived goes once, when it has; that a failing /api/me
// is one plain line and anonymous use goes on; and that the account fills in after load (on a stack with sign-in,
// AUTH=1; elsewhere the page has no account markup, which is checked instead).
// Screenshots: docs/screens/shell-<light|dark|phone>-<1-before-me|2-after-me>.png.
//
// needs the stack (tools/up.sh). usage: node conformance/chat-shell.mjs
import { mkdirSync } from "node:fs";
import { HOST, browser, openHome, pause, startChat, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Home shell");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
const chromium = await browser();
const errors = [];
const HELD_MS = 3000;
const NOT_LOADED = "Your chats could not be loaded. You can still ask.";

const field = (page) => page.locator("#text");
const line = (page) => page.locator('[data-slot="error"]');
const meState = (page) => page.locator("chat-thread").getAttribute("data-me");
const starts = (page) => {
  const seen = [];
  page.on("request", (request) => request.method() === "POST" && request.url().endsWith("/start") && seen.push({ at: Date.now(), token: request.headers()["x-csrftoken"], url: request.url() }));
  return seen;
};
const holdMe = (page, ms = HELD_MS) => {
  const answered = [];
  return page.route("**/api/me", async (route) => {
    await pause(ms);
    await route.continue();
    answered.push(Date.now());
  }).then(() => answered);
};
const chatsOf = (page) => page.locator('chat-sheet [data-slot="rows"] a[data-slot="open"]');

async function visitor(options = {}) {
  const context = await chromium.newContext({ viewport: { width: 1000, height: 780 }, ...options });
  return { context, page: await context.newPage() };
}

console.log("the page is a static asset, served under its own headers");
{
  const { context, page } = await visitor();
  const shell = await context.request.get(`${HOST}/`);
  const headers = shell.headers();
  const dynamic = (await context.request.get(`${HOST}/manifest.webmanifest`)).headers();
  check(shell.status() === 200 && headers["content-type"].startsWith("text/html"), "GET / answers 200 with HTML");
  check(headers["content-security-policy"] === dynamic["content-security-policy"], "its Content-Security-Policy is exactly the one Django sends every other page");
  check(headers["content-security-policy"].includes("script-src 'self'") && headers["content-security-policy"].includes("frame-ancestors 'none'"), "which allows only its own scripts and no embedder");
  check(headers["x-frame-options"] === "DENY" && headers["x-content-type-options"] === "nosniff" && headers["referrer-policy"] === "same-origin", "with X-Frame-Options, nosniff and the same-origin referrer policy");
  check(headers["cross-origin-opener-policy"] === dynamic["cross-origin-opener-policy"], `and the same opener policy (${headers["cross-origin-opener-policy"]})`);
  check(/max-age=60/.test(headers["cache-control"]) && /must-revalidate/.test(headers["cache-control"]), `cached for a minute and then revalidated (${headers["cache-control"]})`);
  check(!("set-cookie" in headers) && !("vary" in headers), "it sets no cookie and varies on nothing: no Worker or Django had a hand in it");
  const body = await shell.text();
  check(!/csrf-token/.test(body) && !/csrfmiddlewaretoken" value="[^"]/.test(body), "its markup holds no CSRF token");
  check(/data-me-url="\/api\/me"/.test(body) && !/Traceback|ada@example/.test(body), "and names /api/me as where the visitor's own part comes from");
  const me = await context.request.get(`${HOST}/api/me`);
  const cookies = me.headersArray().filter((h) => h.name.toLowerCase() === "set-cookie").map((h) => h.value);
  check(cookies.some((c) => c.startsWith("visitor=")) && cookies.some((c) => c.startsWith("csrftoken=")), "/api/me makes the visitor and CSRF cookies");
  check(cookies.every((c) => !/domain=/i.test(c)), "neither names a Domain: both are the host's alone");
  check(me.headers()["cache-control"] === "no-store, private", `and is never stored (${me.headers()["cache-control"]})`);
  check((await context.request.get(`${HOST}/api/me`, { headers: { "Sec-Fetch-Site": "cross-site" } })).status() === 403, "and refused when the browser says the request comes from another site");
  const redirect = await context.request.get(`${HOST}/index.html`, { maxRedirects: 0 });
  check([307, 308].includes(redirect.status()) && new URL(redirect.headers().location, HOST).pathname === "/", "/index.html is not a second address: it goes to /");
  const chat = await context.request.get(`${HOST}/c/${"a".repeat(32)}/`);
  check(chat.status() === 404 && chat.headers()["x-frame-options"] === "DENY" && "content-security-policy" in chat.headers(), "a chat address still reaches the Worker (Django answers it, under its middleware: 404 for a stranger)");
  check((await context.request.get(`${HOST}/manifest.webmanifest`)).status() === 200, "and so does the manifest");
  await context.close();
}

for (const [name, options] of [["light", { colorScheme: "light" }], ["dark", { colorScheme: "dark" }], ["phone", { viewport: { width: 390, height: 780 }, isMobile: true, hasTouch: true }]]) {
  console.log(`\n${name}: the page renders and takes typing while /api/me is held back for ${HELD_MS / 1000} s`);
  const seeded = await visitor(options);
  watchErrors(seeded.page, errors);
  await startChat(seeded.page, "echo: first of the earlier chats");
  await startChat(seeded.page, "echo: second of the earlier chats");
  await seeded.page.waitForFunction(() => document.querySelector("chat-thread:not([data-working])"));
  const page = await seeded.context.newPage();
  watchErrors(page, errors);
  const answered = await holdMe(page);
  const opened = Date.now();
  await page.goto(`${HOST}/`);
  await field(page).waitFor();
  const ready = Date.now() - opened;
  check(ready < HELD_MS - 500 && (await meState(page)) === null, `the page is there after ${ready} ms, with /api/me still on its way`);
  check((await field(page).isEnabled()) && (await page.evaluate(() => document.activeElement === document.querySelector("#text"))), "the composer is enabled and has focus");
  check(await page.locator("chat-starters button").first().isVisible(), "the starters are shown");
  const where = await page.locator('[data-slot="pill"]').boundingBox();
  await page.keyboard.type("Pay for lunch");
  check((await field(page).inputValue()) === "Pay for lunch" && (await page.getByRole("button", { name: "Send", exact: true }).isEnabled()), "typing works and Send is on");
  await page.getByRole("button", { name: "Send ₦5,000 to a friend", exact: true }).click();
  check((await field(page).inputValue()) === "Send ₦5,000 to ", "a starter that needs the person fills the field");
  await page.keyboard.type("Ada");
  check(!(await chatsOf(page).count()), "the drawer has no chats yet, and nothing is said about it");
  await page.screenshot({ path: `${screens}shell-${name}-1-before-me.png` });
  await page.waitForFunction(() => document.querySelector("chat-thread").dataset.me === "loaded", null, { timeout: 15000 });
  check(answered.length === 1 && (await meState(page)) === "loaded", "then /api/me answers once and the page has it");
  check((await field(page).inputValue()) === "Send ₦5,000 to Ada" && (await page.evaluate(() => document.activeElement === document.querySelector("#text"))), "what was typed is still there and the field still has focus");
  const after = await page.locator('[data-slot="pill"]').boundingBox();
  check(Math.abs(after.y - where.y) < 2 && Math.abs(after.x - where.x) < 2, "and the composer did not move");
  check(await page.getByRole("button", { name: "Chats" }).isVisible(), "the chats button has appeared");
  await page.screenshot({ path: `${screens}shell-${name}-2-after-me.png` });
  await page.getByRole("button", { name: "Chats" }).click();
  await page.locator("chat-sheet dialog[open]").waitFor();
  check((await chatsOf(page).count()) === 2, "the drawer lists the visitor's two chats");
  check((await chatsOf(page).first().innerText()).startsWith("echo: second"), "newest first");
  check((await page.getByRole("button", { name: "Delete chat" }).count()) === 2, "each with its delete button");
  await seeded.context.close();
}

console.log("\na first message sent before the token has arrived");
{
  const { context, page } = await visitor();
  watchErrors(page, errors);
  const sent = starts(page);
  const answered = await holdMe(page);
  await page.goto(`${HOST}/`);
  await field(page).waitFor();
  const before = await page.locator('[data-slot="pill"]').boundingBox();
  await page.keyboard.type("echo: late token");
  await page.keyboard.press("Enter");
  await pause(1200);
  check(sent.length === 0, "nothing is sent while the token is on its way");
  check((await field(page).inputValue()) === "echo: late token" && (await line(page).isHidden()), "the text stays in the field and no error shows");
  const during = await page.locator('[data-slot="pill"]').boundingBox();
  check(during.y === before.y && during.height === before.height, "and the composer stays where it is");
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//, { timeout: 15000 });
  await page.locator("chat-thread:not([data-draft])").waitFor();
  check(sent.length === 1 && sent[0].at >= answered[0] && Boolean(sent[0].token), "once it has, the message goes once, with the token");
  await page.locator(".self-end").first().waitFor();
  check((await page.locator(".self-end").allInnerTexts()).join() === "echo: late token", "and is the chat's first message");
  check((await page.locator('[data-slot="error"]').isHidden()) && (await field(page).inputValue()) === "", "with no error and the field emptied");
  await context.close();
}
{
  const { context, page } = await visitor();
  watchErrors(page, errors);
  const sent = starts(page);
  const answered = await holdMe(page);
  await page.goto(`${HOST}/`);
  await page.getByRole("button", { name: "What can you do?", exact: true }).click();
  await pause(800);
  check(sent.length === 0 && (await page.locator("chat-starters button:disabled").count()) > 0, "a starter pressed at once waits too, and its row is off, so a second press cannot send again");
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//, { timeout: 15000 });
  check(sent.length === 1 && sent[0].at >= answered[0], "and it goes once, after the token");
  await context.close();
}

console.log("\n/api/me fails");
{
  const { context, page } = await visitor();
  const sent = starts(page);
  let asked = 0;
  let broken = true;
  await page.route("**/api/me", (route) => {
    asked += 1;
    return broken ? route.fulfill({ status: 500, contentType: "text/plain", body: "boom" }) : route.continue();
  });
  await page.goto(`${HOST}/`);
  await page.waitForFunction(() => document.querySelector("chat-thread").dataset.me === "failed");
  const said = line(page);
  check((await said.innerText()) === NOT_LOADED && (await said.isVisible()), `one plain line says so: "${NOT_LOADED}"`);
  check((await page.locator('[role="alert"]:visible').count()) === 1, "and it is the only alert on the page");
  const signIn = (await page.locator("chat-account").count()) === 1;
  check((await page.getByRole("button", { name: "Chats" }).isVisible()) === signIn && (await field(page).isEnabled()), `nothing else changes: the composer is usable and the chats button is ${signIn ? "there, as sign-in is on" : "not there"}`);
  await page.screenshot({ path: `${screens}shell-light-3-me-failed.png` });
  await page.keyboard.type("echo: nobody answered");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => /Could not reach the server/.test(document.querySelector('[data-slot="error"]').textContent));
  check(asked === 2 && sent.length === 0, "a send asks /api/me once more, sends nothing without a token, and says so");
  check((await field(page).inputValue()) === "echo: nobody answered" && (await field(page).isEnabled()), "the message is kept in the field");
  broken = false;
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//, { timeout: 15000 });
  check(sent.length === 1 && Boolean(sent[0].token), "when /api/me answers again the same message goes: anonymous use did not need the first answer");
  await context.close();
}
{
  const { context, page } = await visitor();
  let asked = 0;
  await page.route("**/api/me", (route) => {
    asked += 1;
    return asked === 1 ? route.abort() : route.continue();
  });
  await page.goto(`${HOST}/`);
  await page.waitForFunction(() => document.querySelector("chat-thread").dataset.me === "failed");
  check((await line(page).innerText()) === NOT_LOADED, "a request that never arrived is the same one line");
  await page.keyboard.type("echo: second try");
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//, { timeout: 15000 });
  await page.locator(".self-end").first().waitFor();
  check(asked === 2 && (await page.locator(".self-end").allInnerTexts()).join() === "echo: second try", "the first send asks again and goes through");
  check(await line(page).isHidden(), "and the line is gone");
  await context.close();
}

console.log("\nthe account fills in after load");
{
  const { context, page } = await visitor({ colorScheme: "light" });
  watchErrors(page, errors);
  const signInOn = (await context.request.get(`${HOST}/api/me`).then((r) => r.json())).signIn !== null;
  await page.route("**/api/me", async (route) => {
    const real = await route.fetch();
    const body = await real.json();
    await pause(1200);
    await route.fulfill({ response: real, json: { ...body, account: { email: "ada@example.com", initial: "A" }, memory: true } });
  });
  const firebase = [];
  page.on("request", (request) => /googleapis|gstatic|firebase|apis\.google|firebase-auth/.test(request.url()) && firebase.push(request.url()));
  await page.goto(`${HOST}/`);
  if (!signInOn) {
    await page.waitForFunction(() => document.querySelector("chat-thread").dataset.me === "loaded");
    check((await page.locator("chat-account").count()) === 0 && (await page.getByText("Continue with Google").count()) === 0, "sign-in is off here: the page has no account markup, and /api/me names none");
    check((await page.locator("chat-memory").count()) === 0 && (await page.getByRole("button", { name: "Chats" }).isHidden()), "nor a memory sheet or a chats button, whatever a response claims");
  } else {
    check(await page.getByRole("button", { name: "Chats" }).isVisible(), "sign-in is on: the chats button is there from the first paint");
    await page.getByRole("button", { name: "Chats" }).click();
    await page.locator("chat-sheet dialog[open]").waitFor();
    check((await page.locator("chat-account button").count()) === 0, "the drawer's account part is empty until /api/me answers");
    await page.waitForFunction(() => document.querySelector("chat-thread").dataset.me === "loaded");
    check(await page.getByText("ada@example.com").isVisible() && (await page.locator('chat-account [data-slot="initial"]').innerText()) === "A", "then it shows the email and the initial");
    check((await page.getByRole("button", { name: "Sign out" }).isVisible()) && (await page.getByRole("button", { name: "What 234 remembers" }).isVisible()), "with Sign out and the memory entry");
    check((await page.getByText("Continue with Google").count()) === 0, "and no sign-in button");
    check((await page.locator("chat-memory dialog").count()) === 1, "the memory sheet exists once the account does");
    check(firebase.length === 0, "the Firebase SDK was not loaded: only a press, or a redirect that comes back, loads it");
    await page.screenshot({ path: `${screens}shell-light-4-account.png` });
  }
  await context.close();
}

check(errors.length === 0, `no page error and no policy violation in any of it${errors.length ? `: ${errors.slice(0, 3).join(" | ")}` : ""}`);
await chromium.close();
finish();
