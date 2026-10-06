// SPDX-License-Identifier: AGPL-3.0-or-later
// How a quote ended reaches the conversation. In a host that is not this one (Claude, ChatGPT), the card sends it
// as a message once, when the person's own action or a live poll shows it ending, so the model answers at once. A
// reloaded conversation, which shows the card again from its old result, sends nothing more. In this app's own
// chat the host writes the outcome into the thread, so the card only updates the model's context there.
// usage: node conformance/card-outcome-hosts.mjs   (the connectors on CHECKOUT_URL)
import { spawn } from "node:child_process";
import { chromium } from "playwright";
import { CHECKOUT, freshLedger, suite } from "./lib.mjs";

const { check, finish } = suite("A card's outcome in the conversation");
const PORT = Number(process.env.CONFORMANCE_PORT ?? 8932);
await freshLedger();
const server = spawn("node", [new URL("server.mjs", import.meta.url).pathname], {
  env: { ...process.env, PORT: String(PORT), CHECKOUT_URL: CHECKOUT },
  stdio: ["ignore", "pipe", "inherit"],
});
await new Promise((resolve) => server.stdout.on("data", (d) => String(d).includes("on http") && resolve()));
const browser = await chromium.launch();
const URI = "ui://paystack-pay/card.html";

async function declined(variant) {
  const page = await (await browser.newContext({ viewport: { width: 420, height: 800 } })).newPage();
  await page.goto(`http://localhost:${PORT}/`);
  await page.evaluate(([u, v]) => window.__mount(u, v), [URI, variant]);
  const card = page.frameLocator("#card");
  await card.getByRole("button", { name: "Decline" }).click();
  await card.getByText("Declined").first().waitFor({ timeout: 10000 });
  await page.waitForTimeout(500);
  const log = await page.evaluate(() => window.__log);
  return { page, quote: await page.evaluate(() => window.__quote), log };
}
const kinds = (log, kind) => log.filter((e) => e.kind === kind).map((e) => e.detail);

try {
  console.log("\nanother host");
  const { page, quote, log } = await declined("plain");
  const messages = kinds(log, "message");
  check(messages.length === 1 && /Declined|declined/.test(messages[0]), `the decline is sent as one message (${messages[0]?.slice(0, 70)})`);
  check(kinds(log, "modelcontext").length === 1, "and the model's context says it too");

  await page.reload();
  await page.evaluate(([u, q]) => window.__mount(u, "plain", q), [URI, quote]);
  const card = page.frameLocator("#card");
  await card.getByText("Declined").first().waitFor({ timeout: 10000 });
  await page.waitForTimeout(2500);
  check(kinds(await page.evaluate(() => window.__log), "message").length === 0, "a reloaded conversation shows the card again and sends nothing");

  console.log("\nthis app's own host");
  const own = await declined("own");
  check(kinds(own.log, "message").length === 0, "no message: the host writes the outcome into the thread");
  check(kinds(own.log, "modelcontext").length === 1, "the model's context is updated as before");
} finally {
  await browser.close();
  server.kill();
}
finish();
