// SPDX-License-Identifier: AGPL-3.0-or-later
// The approval card in hosts that are not this one: a host that says nothing about a sandbox (as Claude Desktop and
// ChatGPT are unknown to), one that lists Paystack's origins but offers no full screen or refuses it, and one whose own
// policy for the card blocks them. In each the card opens the checkout link as it always did, requests nothing from
// Paystack's popup script, and shows nothing to read. The hosts are built on the official ext-apps AppBridge.
//
// needs the stack with the rig (the connector returns the access code): `PAYSTACK_RIG=fake tools/up.sh`.
// usage: PORT_BASE=8920 node conformance/inline-checkout-hosts.mjs
import { spawn } from "node:child_process";
import { chromium } from "playwright";
import { CHECKOUT, freshLedger, seen, suite } from "./lib.mjs";
import { paystackStub } from "./paystack-stub.mjs";

const { check, finish } = suite("Approval card in other hosts");
const PORT = Number(process.env.CONFORMANCE_PORT ?? 8931);
await freshLedger();
const server = spawn("node", [new URL("server.mjs", import.meta.url).pathname], {
  env: { ...process.env, PORT: String(PORT), CHECKOUT_URL: CHECKOUT },
  stdio: ["ignore", "pipe", "inherit"],
});
await new Promise((resolve) => server.stdout.on("data", (d) => String(d).includes("on http") && resolve()));
const browser = await chromium.launch();

const CASES = [
  ["plain", "a host that declares no sandbox and no display mode"],
  ["no-fullscreen", "a host that lists Paystack's origins but offers no full screen"],
  ["claims", "a host that lists them and offers full screen, then refuses it"],
  ["blocks", "a host that lists them and goes full screen, but whose policy for the card does not allow them"],
];

try {
  for (const [variant, what] of CASES) {
    console.log(`\n${what}`);
    const context = await browser.newContext({ viewport: { width: 420, height: 800 } });
    const requests = await paystackStub(context);
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`http://localhost:${PORT}/`);
    await page.evaluate(([u, v]) => window.__mount(u, v), ["ui://paystack-pay/card.html", variant]);
    const card = page.frameLocator("#card");
    await card.getByRole("button", { name: /Approve/ }).waitFor({ timeout: 20000 });
    const log = () => page.evaluate(() => window.__log);
    await card.getByRole("button", { name: /Approve/ }).click();
    const opened = async () => (await log()).find((e) => e.kind === "openlink");
    let link;
    for (let i = 0; i < 100 && !(link = await opened()); i += 1) await page.waitForTimeout(100);
    check(Boolean(link) && link.detail.startsWith("https://checkout.paystack.com/rig"), `the checkout link is opened through ui/open-link (${link?.detail?.slice(0, 44)})`);
    const wanted = variant === "claims" ? ["https://js.paystack.co/v2/inline.js"] : [];
    check(JSON.stringify(requests) === JSON.stringify(wanted), `Paystack's origins were asked for ${wanted.length ? "the script alone: no popup was shown" : "nothing: the popup was never tried"}`);
    check(variant !== "claims" || (await log()).some((e) => e.kind === "displaymode" && e.detail === "fullscreen"), "the card asked the host for full screen and was refused, or the popup was not tried");
    check(await seen(card.getByRole("button", { name: /Open checkout/ }).waitFor({ timeout: 5000 })), "the card waits at the checkout as it does today");
    const text = await card.locator("body").innerText();
    check(!/error|blocked|could not|failed/i.test(text), "and shows no error");
    check(errors.length === 0, `no page errors ${errors.join("; ")}`);
    await context.close();
  }
} finally {
  await browser.close();
  server.kill();
}
finish();
