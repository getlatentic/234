// SPDX-License-Identifier: AGPL-3.0-or-later
// Shared by the browser conformance runs: where the stack is, and a tiny PASS/FAIL reporter.
import { chromium } from "playwright";

const port = Number(process.env.PORT_BASE ?? 8900);
export const HOST = process.env.HOST_URL ?? `http://localhost:${port + 1}`;
export const CHECKOUT = process.env.CHECKOUT_URL ?? `http://localhost:${port}`;
export const MODEL = process.env.MODEL_URL ?? `http://127.0.0.1:${port + 2}`;
export const EVENTS_SECRET = process.env.EVENTS_SECRET ?? "dummy-local-events-secret";

/**
 * Empties the connectors' ledger through the stack's test route, so a suite that approves payments spends from
 * the whole daily limit and not from what the suites before it left. Refuses loudly when the route is off.
 */
export async function freshLedger(connectors = CHECKOUT) {
  const reply = await fetch(`${connectors}/test/reset`, { method: "POST" });
  if (!reply.ok) throw new Error(`${connectors}/test/reset answered ${reply.status}: start the stack with tools/up.sh (test routes on)`);
}

export const seen = (promise) => promise.then(() => true, () => false);
export const pause = (ms) => new Promise((done) => setTimeout(done, ms));

export function suite(title) {
  let failed = 0;
  console.log(title);
  return {
    check(ok, what) {
      console.log(`  ${ok ? "PASS" : "FAIL"}  ${what}`);
      if (!ok) failed += 1;
    },
    finish() {
      console.log(failed === 0 ? "\nAll checks passed." : `\n${failed} check(s) failed.`);
      process.exit(failed === 0 ? 0 : 1);
    },
  };
}

/** Errors a page raises, including Content-Security-Policy violations, which the browser logs as errors. */
export function watchErrors(page, into = []) {
  page.on("pageerror", (error) => into.push(String(error)));
  page.on("console", (message) => message.type() === "error" && into.push(message.text()));
  return into;
}

export async function browser() {
  return chromium.launch();
}


/** Waits until no turn is open: the round button offers Send again (it is Stop while a reply is on its way). */
export const settled = (page, timeout = 15000) => page.locator("chat-thread:not([data-working])").waitFor({ state: "attached", timeout });

export async function say(page, text) {
  await settled(page);
  await page.fill("#text", text);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await page.waitForFunction(() => !document.querySelector("#text").value || !document.querySelector('[data-slot="error"]').classList.contains("hidden"));
}

/** Sends the first message from the ready composer and returns the id of the chat it made. */
export async function sendFirst(page, text) {
  await say(page, text);
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  await page.locator("chat-thread:not([data-draft])").waitFor();
  return new URL(page.url()).pathname.split("/")[2];
}

/** Opens the home page and waits until it has what /api/me says about the visitor (chats, account); returns the page's own response. */
export async function openHome(page, query = "") {
  const response = await page.goto(`${HOST}/${query}`);
  await page.locator("chat-thread[data-me]").waitFor({ state: "attached" });
  return response;
}

/** The CSRF token /api/me gives the page's visitor, asked from inside the page (its cookies). */
export const csrfOf = (page) => page.evaluate(async () => (await (await fetch("/api/me", { credentials: "same-origin" })).json()).csrf);

/** Opens the home page (with a query, if given) and starts a chat the way a person does. */
export async function startChat(page, text, query = "") {
  await openHome(page, query);
  return sendFirst(page, text);
}

export async function modelRequests() {
  return (await fetch(`${MODEL}/v1/_requests`)).json();
}

/** A quote.finished MCP event to the host's /hooks/events, signed as the connectors sign it (Standard Webhooks,
 * with the key the host derives from EVENTS_SECRET: turns/quote_events.py). */
export async function signedEvent(quoteId, state = "settled") {
  const { createHmac } = await import("node:crypto");
  const key = createHmac("sha256", EVENTS_SECRET).update("234-mcp-events").digest();
  const id = `evt_${quoteId}_${state}`;
  const stamp = Math.floor(Date.now() / 1000);
  const data = { quote_id: quoteId, connector: "paystack-pay", state, amount_kobo: 250000, description: "Lunch" };
  const body = JSON.stringify({ eventId: id, name: "quote.finished", timestamp: new Date().toISOString(), data, cursor: null });
  const signature = `v1,${createHmac("sha256", key).update(`${id}.${stamp}.${body}`).digest("base64")}`;
  return fetch(`${HOST}/hooks/events`, { method: "POST", body, headers: { "content-type": "application/json", "webhook-id": id, "webhook-timestamp": String(stamp), "webhook-signature": signature } });
}

/** The colour a design token has right now on the page, as the browser computes it: "rgb(r, g, b)". */
export const tokenColor = (page, name) =>
  page.evaluate((token) => {
    const probe = document.createElement("i");
    probe.style.background = `var(--${token})`;
    document.body.append(probe);
    const colour = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return colour;
  }, name);

/**
 * The card inside its sandbox: the frame in the chat page is the sandbox proxy (another origin), and the card is
 * the frame the proxy made. `cardIn` takes the page and the outer frame's selector; `inCard` a locator for one
 * <card-frame> element.
 */
export const inCard = (cardFrameElement) => cardFrameElement.frameLocator("iframe").frameLocator("iframe");
export const cardIn = (page, selector = "card-frame iframe") => page.frameLocator(selector).first().frameLocator("iframe");
/** The card's own frame (the one that runs the card), as Playwright's Frame, for evaluating in it. */
export const cardFrames = (page) => page.frames().filter((f) => new URL(f.url()).pathname === "/view");

/** Opens the chats drawer and waits until it has stopped sliding in, so a screenshot shows it as it rests. */
export async function openDrawer(page) {
  await page.getByRole("button", { name: "Chats" }).click();
  const dialog = page.locator("chat-sheet dialog[open]");
  await dialog.waitFor();
  await dialog.evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)));
  await page.waitForTimeout(50);
}

/** What a person does in the Firebase Auth emulator's "Google" page, a popup or the tab itself: pick the account
 * if it exists, else add it. A cold emulator now and then drops a click, or the email typed before its form was
 * ready: each try fills the field again if it lost the email, and presses until the popup closes or the tab
 * leaves the emulator. */
export async function chooseGoogleAccount(where, email) {
  const handler = /\/emulator\/auth\/handler/;
  const there = () => !where.isClosed() && handler.test(where.url());
  const gone = () => Promise.race([
    where.waitForEvent("close", { timeout: 8000 }),
    where.waitForURL((url) => !handler.test(url.href), { timeout: 8000 }),
  ]).catch(() => {});
  await where.locator("#accounts-list").waitFor({ state: "visible", timeout: 15000 });
  const existing = where.locator("li.js-reuse-account", { hasText: email });
  if (await existing.count()) {
    for (let tries = 0; tries < 3 && there(); tries += 1) {
      await existing.click({ timeout: 20000 }).catch(() => {});
      await gone();
    }
    return;
  }
  const field = where.locator("#email-input");
  for (let tries = 0; tries < 4 && there(); tries += 1) {
    if (!(await field.isVisible().catch(() => false))) {
      await where.locator("#add-account-button button").click({ timeout: 20000 }).catch(() => {});
      await field.waitFor({ state: "visible", timeout: 8000 }).catch(() => {});
    }
    if ((await field.inputValue().catch(() => "")) !== email) await field.fill(email).catch(() => {});
    await where.locator("#sign-in").click({ timeout: 20000 }).catch(() => {});
    await gone();
  }
}

/** Whether the Firebase SDK's relay iframe in `page` has loaded: the emulator's sign-in popup hands its result
 * to that iframe, which passes it to the page. */
export async function relayReady(page, timeout = 8000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    for (const frame of page.frames().filter((f) => f.url().includes("/emulator/auth/iframe"))) {
      if (await frame.evaluate(() => document.readyState === "complete" && typeof gapi === "object").catch(() => false)) return true;
    }
    await pause(200);
  }
  return false;
}

/** Presses the button that opens Google's sign-in (`press`) and returns the popup once the page's relay iframe
 * has loaded. In headless Chromium about one sign-in in twenty leaves that iframe loading forever: its response
 * arrives, its document never parses, and the popup can then hand its result to no one. That is not waited
 * on: the popup is closed, the page reloaded, `reopen` brings the button back, and it is pressed again, at most
 * twice more, each time with a note in the output. */
export async function popupWhenRelayReady(page, press, reopen = async () => {}) {
  for (let attempt = 0; ; attempt += 1) {
    const opened = page.waitForEvent("popup");
    await press();
    const window = await opened;
    if (await relayReady(page)) return window;
    if (attempt === 2) throw new Error("the Firebase relay iframe did not load in three presses");
    console.log("  note  the Firebase relay iframe did not load; the page is reloaded and the button pressed again");
    await window.close();
    await page.reload();
    await reopen();
  }
}
