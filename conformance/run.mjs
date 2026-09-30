// SPDX-License-Identifier: AGPL-3.0-or-later
// Drives each card through the official ext-apps AppBridge in a real browser (Playwright) and
// checks the handshake, tool-result delivery, size reports, an app-only tools/call, open-link,
// polling to a receipt, and the note to the model.
//
// usage: node conformance/run.mjs   (Worker on CHECKOUT_URL, default the stack's connector Worker (PORT_BASE),
//        started with ALT_CARDS=react=react-card.html,probe=probe-card.html,official=card-official.html to include the React card)
import { spawn } from "node:child_process";
import { chromium } from "playwright";
import { CHECKOUT, freshLedger } from "./lib.mjs";

const WORKER = CHECKOUT;
const PORT = Number(process.env.CONFORMANCE_PORT ?? 8930);
const CARDS = {
  "django-template card": "ui://paystack-pay/card.html",
  "django card, client on the official App class": "ui://paystack-pay/card-official.html",
  "react card (unchanged)": "ui://paystack-pay/card-react.html",
  "probe card (official App class)": "ui://paystack-pay/card-probe.html",
};

await freshLedger();
const server = spawn("node", [new URL("server.mjs", import.meta.url).pathname], {
  env: { ...process.env, PORT: String(PORT), CHECKOUT_URL: WORKER },
  stdio: ["ignore", "pipe", "inherit"],
});
await new Promise((resolve) => server.stdout.on("data", (d) => String(d).includes("on http") && resolve()));

let failed = 0;
const check = (ok, what) => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${what}`);
  if (!ok) failed += 1;
};
const until = async (fn, what, ms = 8000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (await fn()) return true;
    await new Promise((r) => setTimeout(r, 100));
  }
  console.log(`  (timed out waiting for ${what})`);
  return false;
};

async function probeChecks(page, until, check) {
  const frame = () => page.frames().find((f) => f !== page.mainFrame());
  const log = () => page.evaluate(() => window.__log);
  const has = async (kind, test = () => true) => (await log()).some((e) => e.kind === kind && test(e.detail));
  const probe = (fn, ...args) => frame().evaluate(([f, a]) => window.probe[f](...a), [fn, args]);
  const results = () => frame().evaluate(() => window.__probe.results);
  const last = async () => (await results()).at(-1);

  check(await until(() => has("initialized"), "initialized"), "official App connected to the official AppBridge");
  await until(async () => (await frame().evaluate(() => window.__probe.token)) !== undefined, "tool result");
  const { quote, token } = await frame().evaluate(() => ({ quote: window.__probe.quote, token: window.__probe.token }));
  check(quote?.phase === "awaiting_approval" && typeof token === "string", "tool-result notification carried the quote and, in _meta, the approval token (for the card only)");

  await probe("callTool", "verify_quote", { quote_id: quote.id });
  let r = await last();
  check(r.ok && r.value.structuredContent.quote.id === quote.id, "app-only tools/call verify_quote: the server's result came back as the JSON-RPC response");
  await probe("callTool", "approve_quote", { quote_id: quote.id, approval_token: token, displayed_amount_kobo: quote.amount.kobo });
  r = await last();
  check(r.ok && r.value.structuredContent.quote.phase === "awaiting_checkout", "app-only tools/call approve_quote with the card's token approved the quote");
  await probe("callTool", "approve_quote", { quote_id: quote.id, approval_token: "wrong", displayed_amount_kobo: quote.amount.kobo });
  r = await last();
  check(r.ok && r.value.isError === true, "the same call without the right token comes back as a tool error, not an approval");
  await probe("callTool", "create_payment_quote", {});
  r = await last();
  check(!r.ok && r.error.includes("not available to cards"), `a model-only tool is refused when a card asks (${r.error})`);

  await probe("message", "Please check my balance");
  check(await has("message", (t) => t === "Please check my balance"), "ui/message reached the host");
  await probe("context", "Card shows: waiting for checkout");
  check(await has("modelcontext", (t) => t.includes("waiting for checkout")), "ui/update-model-context reached the host");
  await probe("openLink", "https://example.com/pay");
  check(await has("openlink", (u) => u === "https://example.com/pay"), "ui/open-link reached the host");
  await probe("openLink", "javascript:alert(1)");
  r = await last();
  check(r.ok && r.value.isError === true, "the host refused a non-web link");
  check(await has("size", (h) => h > 0), "ui/notifications/size-changed reached the host");
}

const browser = await chromium.launch();
try {
  for (const [name, uri] of Object.entries(CARDS)) {
    console.log(`\n${name}  ${uri}`);
    const page = await browser.newPage();
    const events = [];
    page.on("pageerror", (e) => events.push(`pageerror ${e}`));
    await page.goto(`http://localhost:${PORT}/`);
    await page.evaluate((u) => window.__mount(u), uri);
    if (name.startsWith("probe")) {
      await probeChecks(page, until, check);
      await page.close();
      continue;
    }
    const card = page.frameLocator("#card");
    const log = () => page.evaluate(() => window.__log);
    const has = async (kind, test = () => true) => (await log()).some((e) => e.kind === kind && test(e.detail));

    check(await until(() => has("initialized"), "initialized"), "ui/initialize handshake completed (AppBridge saw ui/notifications/initialized)");
    check(await card.getByText("Demo Kitchen").first().waitFor({ timeout: 8000 }).then(() => true, () => false), "tool result delivered: card shows the merchant");
    check(await card.getByText("₦2,500").first().isVisible(), "card shows the amount");
    check(await until(() => has("size", (h) => h > 100), "size-changed"), "ui/notifications/size-changed reached the host with a height");

    await card.getByRole("button", { name: /Approve/ }).click();
    check(await until(() => has("calltool", (n) => n === "approve_quote"), "approve tools/call"), "app-only tools/call approve_quote proxied through the bridge");
    check(await card.getByRole("button", { name: /Open checkout/ }).waitFor({ timeout: 8000 }).then(() => true, () => false), "card moved to awaiting checkout with the server's answer");
    const opened = (await log()).find((e) => e.kind === "openlink");
    check(Boolean(opened) && opened.detail.includes("/sim/checkout/qt-"), `ui/open-link asked the host to open the checkout (${opened?.detail?.slice(0, 60)})`);

    const reference = opened.detail.split("/").pop();
    await fetch(`${WORKER}/sim/checkout/${reference}/pay`, { method: "POST" });
    check(await card.getByText("Payment received").first().waitFor({ timeout: 12000 }).then(() => true, () => false), "card polled verify_quote and showed the receipt");
    check(await until(() => has("modelcontext", (t) => t.includes("now shows")), "model context"), "ui/update-model-context sent once the card finished");
    check(await has("calltool", (n) => n === "verify_quote"), "verify_quote was called by the card");

    const frame = page.frames().find((f) => f !== page.mainFrame());
    if (name === "django-template card") {
      const reached = await frame.evaluate(() => fetch("/api/quote", { method: "POST" }).then(() => "reached", () => "blocked"));
      check(reached === "blocked", "the sandboxed card has no network of its own (CSP default-src 'none')");
      const refused = await frame.evaluate(() => McpApp.callTool("create_payment_quote", {}).then(() => "allowed", (e) => e.message));
      check(refused.includes("not available to cards"), `host refuses a model-only tool from the card (${refused})`);
    }
    check(events.length === 0, `no page errors ${events.join("; ")}`);
    await page.close();
  }
} finally {
  await browser.close();
  server.kill();
}
console.log(failed === 0 ? "\nAll checks passed." : `\n${failed} check(s) failed.`);
process.exit(failed === 0 ? 0 : 1);
