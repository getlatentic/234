// SPDX-License-Identifier: AGPL-3.0-or-later
// Paystack's popup inside the approval card, in the real chat page behind the sandbox proxy: shown only where it can
// run, the server's record (never the popup's callback) deciding what happened, and the link used, with nothing for the
// person to read, wherever the popup cannot run. Paystack is stood in for by conformance/paystack-stub.mjs at its own
// origins, so the page's real policy decides what loads, and by conformance/paystack-rig.mjs for its API.
//
// needs the stack with the rig: `PAYSTACK_RIG=fake tools/up.sh`. usage: PORT_BASE=8920 node conformance/inline-checkout.mjs
import { readFileSync } from "node:fs";
import { HOST, browser, freshLedger, cardFrames, cardIn, pause, seen, startChat, suite, watchErrors } from "./lib.mjs";
import { paystackStub } from "./paystack-stub.mjs";

const RIG = `http://127.0.0.1:${Number(process.env.PORT_BASE ?? 8900) + 6}`;
const { check, finish } = suite("Paystack popup in the approval card");
await freshLedger();
const chromium = await browser();
const errors = [];

const rig = async (path, body) => (await fetch(`${RIG}${path}`, body ? { method: "POST", body: JSON.stringify(body) } : {})).json();
const paid = async () => {
  const [latest] = (await rig("/rig/state")).slice(-1);
  await rig("/rig/pay", { reference: latest.reference });
};

async function open(script = "works", { viewport = { width: 420, height: 800 } } = {}) {
  const context = await chromium.newContext({ viewport });
  const requests = await paystackStub(context, { script });
  const tabs = [];
  const page = await context.newPage();
  context.on("page", (tab) => tabs.push(tab));
  watchErrors(page, errors);
  const chat = await startChat(page, "Pay ₦2,500 to Demo Kitchen for lunch");
  const card = cardIn(page);
  await card.getByRole("button", { name: /Approve/ }).waitFor({ timeout: 20000 });
  return { context, page, card, chat, requests, tabs };
}

const paystackState = (page) => cardFrames(page)[0]?.evaluate(() => window.__paystack).catch(() => null);
const isFullScreen = (page) => page.evaluate(() => getComputedStyle(document.querySelector("card-frame")).position === "fixed");
const popupFrames = (page) => page.frames().filter((f) => f.url().startsWith("https://checkout.paystack.com/"));
const quiet = async (page, tabs) => (await page.locator("card-frame").innerText()).match(/error|failed|blocked|could not/i) === null && tabs.length === 0;
const until = async (test, ms = 8000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (await test()) return true;
    await pause(100);
  }
  return false;
};

console.log("before the person does anything");
let s = await open();
const line = await s.page.locator("card-frame p").first().innerText();
check(line === "This card loads content from js.paystack.co and checkout.paystack.com", `one quiet line says where the card loads content from (${line})`);
check((await s.page.locator("card-frame p").first().evaluate((p) => p.nextElementSibling.tagName)) === "IFRAME", "it sits above the card, to be read before using it");
check(s.requests.length === 0, "nothing was requested from Paystack before Approve: the script loads when it is needed");
check((await s.page.locator("card-frame").getAttribute("data-uri")) !== null && (await s.page.locator('[role="dialog"]').count()) === 0, "and it is a line, not a dialog");

console.log("what the connector asked for, and what the host granted");
const uri = encodeURIComponent("ui://paystack-pay/card.html");
const served = await (await s.page.request.get(`${HOST}/c/${s.chat}/card?server=paystack-pay&uri=${uri}`)).json();
check(JSON.stringify(served.csp) === JSON.stringify({ resourceDomains: ["https://js.paystack.co"], frameDomains: ["https://checkout.paystack.com"] }), "the resource also asked for connections, a wildcard, data:, a look-alike frame and a base URI of another origin: the host gave the card only Paystack's two");
check(served.permissions && Object.keys(served.permissions).length === 0 && served.sandbox === "allow-scripts allow-same-origin", "no permission, and the sandbox origin only because an approved frame is embedded");
const hostLog = readFileSync(new URL(`../.stack/${process.env.PORT_BASE ?? 8900}/host.log`, import.meta.url), "utf8");
const refusedLines = hostLog.split("\n").map((line) => { try { return JSON.parse(line).msg ?? ""; } catch { return line; } }).filter((message) => message.includes('"card.csp.refused"'));
check(refusedLines.length >= 7 && ["api.evil.example.com", "live.evil.example.com", "*.evil.example.com", "com.evil.example.com", "https://evil.example.com"].every((entry) => refusedLines.some((line) => line.includes(entry))), `the refusals are in the host's log, not on the page (${refusedLines.length} lines)`);
check(!(await s.page.locator("body").innerText()).includes("evil"), "and the person is told nothing about them");

console.log("approve: the popup opens in full screen, in the page");
await s.card.getByRole("button", { name: /Approve/ }).click();
check(await until(async () => (await popupFrames(s.page)).length === 1), "Paystack's checkout is a frame in the card, from Paystack's origin");
check(await isFullScreen(s.page), "the card is in full screen for it, since the popup fills its window");
check(s.tabs.length === 0, "no tab was opened");
const held = await paystackState(s.page);
check(held.opened === 1 && held.codes[0].startsWith("rig"), "the access code the connector returned in _meta was given to resumeTransaction");
const shownText = await s.page.locator("body").innerText();
check(!shownText.includes(held.codes[0]), "and the code is nowhere in the page's visible text (it is inside the checkout link the card already held, as before)");

console.log("a second press, and the popup's own callbacks");
await s.card.getByRole("button", { name: /Open checkout/ }).click({ timeout: 1500 }).catch(() => undefined);
check((await popupFrames(s.page)).length === 1 && (await paystackState(s.page)).opened === 1, "the card behind the popup cannot be pressed a second time: one popup");
await paystackState(s.page);
await cardFrames(s.page)[0].evaluate(() => window.__paystack.popups[0].callbacks.onSuccess());
await pause(2500);
check(!(await isFullScreen(s.page)) && (await s.card.getByText("Payment received").count()) === 0, "onSuccess alone does not make the payment received: the card is back and still waiting for the server");
check(await s.card.getByRole("button", { name: /Open checkout/ }).isVisible(), "and still offers the checkout");
await paid();
check(await seen(s.card.getByText("Payment received").first().waitFor({ timeout: 12000 })), "once the server has verified the payment with Paystack the card shows the receipt");
await s.context.close();

console.log("cancel, and pressing again");
s = await open();
await s.card.getByRole("button", { name: /Approve/ }).click();
await until(async () => (await popupFrames(s.page)).length === 1);
await cardFrames(s.page)[0].evaluate(() => window.__paystack.popups[0].cancelTransaction());
check(await until(async () => !(await isFullScreen(s.page))), "cancelling in the popup returns the card to the page");
check((await s.card.getByRole("button", { name: /Open checkout/ }).isVisible()) && s.tabs.length === 0, "it is still waiting at the checkout, no tab opened, nothing abandoned");
await s.card.getByRole("button", { name: /Open checkout/ }).click();
check(await until(async () => (await popupFrames(s.page)).length === 1), "Open checkout shows the popup again");
check((await paystackState(s.page)).opened === 2, "a fresh popup for the same access code");
console.log("Close, in the bar of the full-screen card, while the popup is up");
await s.page.getByRole("button", { name: "Close full screen" }).click();
check(await until(async () => !(await isFullScreen(s.page))), "returns to the page");
check(await until(async () => (await popupFrames(s.page)).length === 0), "and takes the popup with it");
check(await s.card.getByRole("button", { name: /Open checkout/ }).isVisible(), "the card still offers the checkout");
await s.context.close();

console.log("reload during payment");
s = await open();
await s.card.getByRole("button", { name: /Approve/ }).click();
await until(async () => (await popupFrames(s.page)).length === 1);
const before = s.requests.length;
await s.page.reload();
const again = cardIn(s.page);
await again.getByRole("button", { name: /Open checkout/ }).waitFor({ timeout: 20000 });
check(s.requests.length === before, "after a reload nothing opens by itself");
await again.getByRole("button", { name: /Open checkout/ }).click();
check(await until(async () => (await popupFrames(s.page)).length === 1), "Open checkout shows the popup: the card was handed the code again while the person is at the checkout");
console.log("a second tab");
const other = await s.context.newPage();
watchErrors(other, errors);
const opened = s.requests.length;
await other.goto(`${HOST}/c/${s.chat}/`);
await cardIn(other).getByRole("button", { name: /Open checkout/ }).waitFor({ timeout: 20000 });
await other.waitForTimeout(2500);
check(s.requests.length === opened && (await popupFrames(other)).length === 0, "the card in a second tab shows no popup by itself");
await s.context.close();

console.log("while the popup is still loading");
s = await open("slow");
await s.card.getByRole("button", { name: /Approve/ }).click();
await until(async () => (await popupFrames(s.page)).length === 1);
await cardFrames(s.page)[0].evaluate(() => document.querySelector('[data-action="open-checkout"]')?.click());
await pause(500);
check((await paystackState(s.page)).opened === 1 && (await popupFrames(s.page)).length === 1, "a second press of Open checkout starts no second popup");
await s.page.getByRole("button", { name: "Close full screen" }).click();
check(await until(async () => !(await isFullScreen(s.page)) && (await popupFrames(s.page)).length === 0, 3000), "Close during the load returns the card and takes the popup with it, at once");
await pause(3500);
check((await popupFrames(s.page)).length === 0 && s.tabs.length === 0, "and the popup does not come back when it would have loaded, and no tab is opened");
await s.card.getByRole("button", { name: /Open checkout/ }).click();
check(await until(async () => (await popupFrames(s.page)).length === 1), "Open checkout works again afterwards");
await s.context.close();
s = await open("slow");
await s.card.getByRole("button", { name: /Approve/ }).click();
await until(async () => (await popupFrames(s.page)).length === 1);
await paid();
check(await seen(s.card.getByText("Payment received").first().waitFor({ timeout: 12000 })), "a payment the server confirms while the popup is loading shows the receipt");
check(await until(async () => !(await isFullScreen(s.page)) && (await popupFrames(s.page)).length === 0), "and puts the card back with no popup over it");
await s.context.close();

console.log("wherever it cannot run, the link opens and nothing is shown");
for (const [script, why] of [["missing", "the script does not load"], ["throws", "the script throws"], ["violates", "the script trips the policy"], ["errors-on-load", "the popup reports an error"]]) {
  s = await open(script);
  const tab = s.context.waitForEvent("page", { timeout: 15000 });
  await s.card.getByRole("button", { name: /Approve/ }).click();
  const link = await tab.then((t) => t, () => null);
  check(Boolean(link) && link.url().includes("/sim/checkout/") === false && link.url().includes("checkout.paystack.com"), `${why}: the checkout link is opened (${link?.url().slice(0, 40)})`);
  check(await until(async () => !(await isFullScreen(s.page)) && (await popupFrames(s.page)).length === 0), `${why}: the card is back in the page, no popup left behind`);
  check(await s.card.getByRole("button", { name: /Open checkout/ }).isVisible() && (await quiet(s.page, [])), `${why}: the person reads no error`);
  await s.context.close();
}

console.log("a popup that never loads");
s = await open("never-loads");
const slow = s.context.waitForEvent("page", { timeout: 25000 });
await s.card.getByRole("button", { name: /Approve/ }).click();
const late = await slow.then((t) => t, () => null);
check(Boolean(late), "the link opens after the time limit");
check(!(await isFullScreen(s.page)), "and the card is back in the page");
await s.context.close();

const unexpected = errors.filter((e) => !/Failed to load resource|ERR_FAILED|violates the following Content Security Policy|Refused to load|allow-scripts and allow-same-origin|Uncaught Error: stub/.test(e));
check(unexpected.length === 0, `no page errors ${unexpected.join("; ")}`);
await chromium.close();
finish();
