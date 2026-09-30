// SPDX-License-Identifier: AGPL-3.0-or-later
// The simulated Paystack checkout page in a real browser: its look in light and dark at 320 px, its states,
// its targets, focus rings, contrast, its policy, the way back to the chat, and window.close.
// Screenshots go to docs/screens/checkout-<state>-<scheme>.png.
//
// needs the stack (connectors only). usage: node conformance/sim-checkout.mjs
import { fileURLToPath } from "node:url";
import { CHECKOUT, HOST, browser, freshLedger, seen, suite, watchErrors } from "./lib.mjs";
import { contrastReport } from "./card-checks.mjs";

const { check, finish } = suite("Simulated Paystack checkout page");
const screens = fileURLToPath(new URL("../docs/screens/", import.meta.url));
const run = Math.random().toString(36).slice(2, 8);
let rpc = 0;
let seq = 0;

const call = async (connector, name, args) => {
  const body = { jsonrpc: "2.0", id: ++rpc, method: "tools/call", params: { name, arguments: args } };
  const reply = await fetch(`${CHECKOUT}/${connector}/mcp`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(body),
  });
  return (await reply.json()).result;
};

/** A payment approved on the connector: the checkout address the card would open. */
async function checkoutFor({ merchant = "Demo Kitchen", description = "Lunch", kobo = 250_000 } = {}) {
  const made = await call("paystack-pay", "create_payment_quote", {
    amount_kobo: kobo, amount_as_user_said: `₦${kobo / 100}`, description, merchant,
    idempotency_key: `sim-page-${run}-${String(++seq).padStart(3, "0")}`,
  });
  const quote = made.structuredContent.quote;
  const approved = await call("paystack-pay", "approve_quote", {
    quote_id: quote.id, approval_token: made._meta.approvalToken, displayed_amount_kobo: quote.amount.kobo,
  });
  return { url: approved.structuredContent.quote.checkoutUrl, quote };
}

const CHAT = `/c/${"a1".repeat(16)}/`;
await freshLedger();
const chromium = await browser();
const errors = [];

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}, 320 px wide`);
  const context = await chromium.newContext({
    viewport: { width: 320, height: 640 }, deviceScaleFactor: 2, hasTouch: true, colorScheme: scheme,
  });
  const states = {};
  for (const [state, button] of [["paid", "Pay with a test card"], ["declined", "Use a declined card"], ["closed", "Close without paying"]]) {
    const { url } = await checkoutFor();
    const page = await context.newPage();
    watchErrors(page, errors);
    const opened = await page.goto(`${url}?back=${CHAT}`);
    if (state === "paid") {
      const policy = opened.headers()["content-security-policy"] ?? "";
      check(/default-src 'none'/.test(policy) && /form-action 'self'/.test(policy) && !/unsafe-inline/.test(policy), "the page is served with a strict policy");
      check(opened.headers()["cache-control"] === "no-store", "and is never cached");

      check((await page.locator("h1").allInnerTexts()).join() === "Demo Kitchen · Lunch", "merchant and description are one line");
      check((await page.locator(".amount").innerText()) === "₦2,500", "the amount is large and reads ₦2,500");
      check((await page.locator(".amount").evaluate((el) => getComputedStyle(el).fontVariantNumeric)).includes("tabular-nums"), "with tabular numerals");
      check((await page.locator(".mode").innerText()).trim() === "Simulated: no money moves", "the simulated line is the small dot line");
      const names = await page.getByRole("button").allInnerTexts();
      check(names.join("|") === "Pay with a test card|Use a declined card|Close without paying", `three actions, in order (${names.join(" | ")})`);
      check((await page.locator("p, h1, button, a").count()) === 6, "and nothing else: a line, who, the amount, three buttons, no paragraph of explanation");
      const small = await page.getByRole("button").evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().height)).filter((h) => h < 44));
      check(small.length === 0, "every target is at least 44 px tall");
      check(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), "no horizontal scroll at 320 px");
      const fits = await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight);
      check(fits, "everything fits one 320 x 640 screen");
      const low = await page.evaluate(contrastReport);
      check(low.length === 0, `every text meets WCAG AA contrast ${JSON.stringify(low)}`);
      await page.keyboard.press("Tab");
      const ring = await page.evaluate(() => { const s = getComputedStyle(document.activeElement); return `${s.outlineStyle} ${s.outlineWidth}`; });
      check(ring === "solid 2px", `the first Tab shows a focus ring on the primary action (${ring})`);
      check((await page.evaluate(() => document.activeElement.textContent)) === "Pay with a test card", "and it is the primary action");
      await page.screenshot({ path: `${screens}checkout-open-${scheme}.png` });
    }
    await page.getByRole("button", { name: button }).click();
    await page.getByRole("status").waitFor();
    states[state] = (await page.getByRole("status").innerText()).trim();
    check(await page.getByRole("button").count() === 0, `${state}: the buttons are gone after the press`);
    check((await page.getByRole("status").count()) === 1, `${state}: one state line`);
    const back = page.getByRole("link", { name: "Return to the chat" });
    check((await back.getAttribute("href")) === `${HOST}${CHAT}`, `${state}: "Return to the chat" goes to the chat the page was opened from`);
    check((await back.evaluate((el) => el.getBoundingClientRect().height)) >= 44, `${state}: and is a 44 px target`);
    check(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), `${state}: no horizontal scroll`);
    const lowState = await page.evaluate(contrastReport);
    check(lowState.length === 0, `${state}: contrast holds ${JSON.stringify(lowState)}`);
    if (scheme === "dark" || state !== "closed") await page.screenshot({ path: `${screens}checkout-${state}-${scheme}.png` });
    await page.close();
  }
  check(states.paid === "Paid" && states.declined === "Declined" && states.closed === "Closed", `the state lines read Paid, Declined and Closed (${Object.values(states).join(", ")})`);
  await context.close();
}

console.log("\nthe page when it does not close by itself");
{
  const context = await chromium.newContext({ viewport: { width: 320, height: 640 } });
  const page = await context.newPage();
  watchErrors(page, errors);
  const { url } = await checkoutFor();
  await page.goto(url);
  await page.getByRole("button", { name: "Pay with a test card" }).click();
  await page.getByRole("status").waitFor();
  await page.waitForTimeout(1800);
  check(!page.isClosed() && (await page.getByRole("status").innerText()).trim() === "Paid", "a tab the person opened stays open and still reads Paid");
  check((await page.getByRole("link", { name: "Return to the chat" }).count()) === 0, "with no link when the chat is not known");
  await context.close();
}

console.log("\nthe page when a card opened it");
for (const features of ["noopener,noreferrer", "noopener", ""]) {
  const context = await chromium.newContext({ viewport: { width: 320, height: 640 } });
  const opener = await context.newPage();
  await opener.goto(`${CHECKOUT}/health`);
  const { url } = await checkoutFor();
  const popup = context.waitForEvent("page");
  await opener.evaluate(([address, how]) => window.open(address, "_blank", how || undefined), [url, features]);
  const window_ = await popup;
  const gone = window_.waitForEvent("close", { timeout: 6000 });
  await window_.getByRole("button", { name: "Pay with a test card" }).click();
  await window_.getByRole("status").waitFor().catch(() => {});
  check(await seen(gone), `a window opened with "${features || "no features"}" is closed by the page after Paid`);
  await context.close();
}

console.log("\nno script, no problem");
{
  const context = await chromium.newContext({ javaScriptEnabled: false, viewport: { width: 320, height: 640 } });
  const page = await context.newPage();
  const { url } = await checkoutFor();
  await page.goto(url);
  await page.getByRole("button", { name: "Use a declined card" }).click();
  check((await page.getByRole("status").innerText()).trim() === "Declined", "the buttons are plain forms: they work with scripts off");
  await context.close();
}

console.log("\nrefusals");
{
  const { url } = await checkoutFor();
  const foreign = await fetch(`${url}/pay`, { method: "POST", headers: { origin: "https://evil.example" } });
  check(foreign.status === 403, "a press posted from another origin is refused");
  const stillOpen = await (await fetch(url)).text();
  check(stillOpen.includes("Pay with a test card"), "and leaves the payment open");
  const hostile = await fetch(`${url}?back=//evil.example${CHAT}`);
  check(!(await hostile.text()).includes("evil.example"), "a way back that is not a chat path is not carried");
  const hostileMerchant = await checkoutFor({ merchant: "<img src=x onerror=alert(1)>", description: '"><script>alert(1)</script>' });
  const body = await (await fetch(hostileMerchant.url)).text();
  check(!body.includes("<img") && !body.includes("<script>alert"), "what the model wrote is escaped");
  check((await fetch(`${CHECKOUT}/sim/checkout/no-such-reference`)).status === 404, "an unknown checkout is 404");
}

const unexpected = errors.filter((e) => !/Failed to load resource/.test(e));
check(unexpected.length === 0, `no page errors or policy violations ${unexpected.join("; ")}`);
await chromium.close();
finish();
