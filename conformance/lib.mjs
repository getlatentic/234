// SPDX-License-Identifier: AGPL-3.0-or-later
// Shared by the browser conformance runs: where the stack is, and a tiny PASS/FAIL reporter.
import { chromium } from "playwright";

const port = Number(process.env.PORT_BASE ?? 8900);
export const HOST = process.env.HOST_URL ?? `http://localhost:${port + 1}`;
export const CHECKOUT = process.env.CHECKOUT_URL ?? `http://localhost:${port}`;
export const MODEL = process.env.MODEL_URL ?? `http://127.0.0.1:${port + 2}`;
export const WEBHOOK_SECRET = process.env.WEBHOOK_SECRET ?? "dummy-local-webhook-secret";

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

export async function signedWebhook(quoteId) {
  const { createHmac } = await import("node:crypto");
  const body = JSON.stringify({ quote_id: quoteId });
  const signature = `sha256=${createHmac("sha256", WEBHOOK_SECRET).update(body).digest("hex")}`;
  return fetch(`${HOST}/hooks/payment`, { method: "POST", body, headers: { "content-type": "application/json", "X-Signature": signature } });
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
