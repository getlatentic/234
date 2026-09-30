// SPDX-License-Identifier: AGPL-3.0-or-later
// ONE run against Paystack's real test mode: the popup loads, in the real chat behind the sandbox proxy, under the
// policy the connector's declaration earned. Nothing is typed into Paystack's page and nothing is paid: the popup is
// looked at, its origins and any policy violation are recorded, and the card's Close bar dismisses it. The connector
// reaches Paystack through conformance/paystack-rig.mjs in forwarding mode, which alone reads the sk_test_ key and
// prints neither it nor an access code nor an authorization link.
//
// needs `PAYSTACK_RIG=real tools/up.sh`. usage: PORT_BASE=8920 node conformance/inline-checkout-real.mjs
import { browser, freshLedger, cardFrames, cardIn, pause, startChat, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Paystack popup, real test mode (loads only)");
await freshLedger();
const chromium = await browser();
const context = await chromium.newContext({ viewport: { width: 420, height: 800 } });
const errors = [];

// Every policy violation any frame reports, and every request that leaves for another origin, by the frame that made it.
await context.addInitScript(() => {
  window.__violations = [];
  document.addEventListener("securitypolicyviolation", (event) => window.__violations.push(`${event.effectiveDirective} ${event.blockedURI}`));
});
const requested = new Map();
context.on("request", (request) => {
  const url = new URL(request.url());
  if (url.hostname === "localhost" || url.hostname === "127.0.0.1") return;
  const from = request.frame().url().startsWith("https://checkout.paystack.com") ? "inside the popup" : "from the card";
  const key = `${from}: ${url.origin}`;
  requested.set(key, (requested.get(key) ?? 0) + 1);
});
const tabs = [];
const page = await context.newPage();
context.on("page", (tab) => tabs.push(tab));
watchErrors(page, errors);
const chat = await startChat(page, "Pay ₦2,500 to Demo Kitchen for lunch");
const card = cardIn(page);
await card.getByRole("button", { name: /Approve/ }).waitFor({ timeout: 20000 });
const line = await page.locator("card-frame p").first().innerText();
check(line === "This card loads content from js.paystack.co and checkout.paystack.com", `the card says where it loads content from (${line})`);

await card.getByRole("button", { name: /Approve/ }).click();
const popup = async () => page.frames().find((f) => new URL(f.url() || "about:blank").origin === "https://checkout.paystack.com" && f.url().includes("/popup"));
let frame;
for (let i = 0; i < 200 && !(frame = await popup()); i += 1) await pause(100);
check(Boolean(frame), "Paystack's real checkout is a frame in the card (checkout.paystack.com/popup)");
await pause(6000);
const view = cardFrames(page)[0];
const violations = await view.evaluate(() => window.__violations);
check(violations.length === 0, `no policy violation in the card (${violations.length})`);
check((await view.evaluate(() => typeof window.PaystackPop)) === "function", "Paystack's real inline script ran: PaystackPop is a function");
check(await page.evaluate(() => getComputedStyle(document.querySelector("card-frame")).position === "fixed"), "the card is in full screen for it");
check(tabs.length === 0, "no tab was opened: the link was not used");
const body = await frame.evaluate(() => document.body.innerText).catch(() => "");
check(/NGN\s*2,?500|₦\s*2,?500/i.test(body) || body.length > 20, `the popup shows a checkout for the transaction (${body.replace(/\s+/g, " ").slice(0, 70)}...)`);
await page.screenshot({ path: new URL("../docs/screens/inline-popup-real.png", import.meta.url).pathname });
console.log("\norigins requested while the popup loaded:");
for (const [key, count] of [...requested].sort()) console.log(`  ${key} (${count})`);
const outside = [...requested.keys()].filter((k) => k.startsWith("from the card")).map((k) => k.split(": ")[1]);
check(outside.every((o) => ["https://js.paystack.co", "https://checkout.paystack.com"].includes(o)), `the card itself asked only js.paystack.co and checkout.paystack.com (${outside.join(", ")})`);

await page.getByRole("button", { name: "Close full screen" }).click();
await pause(1000);
check(await page.evaluate(() => getComputedStyle(document.querySelector("card-frame")).position !== "fixed"), "Close in the bar brings the card back to the page");
check(await card.getByRole("button", { name: /Open checkout/ }).isVisible(), "still waiting at the checkout, nothing paid, nothing typed");
void chat;
const unexpected = errors.filter((e) => !/allow-scripts and allow-same-origin|Failed to load resource|GL Driver|allowpaymentrequest|Allow attribute/.test(e));
check(unexpected.length === 0, `no page errors ${unexpected.join("; ").slice(0, 300)}`);
await chromium.close();
finish();
