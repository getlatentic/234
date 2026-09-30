// SPDX-License-Identifier: AGPL-3.0-or-later
// The starters in the real page against a real model (tools/real-model.sh, not part of tools/check.sh: it makes
// model calls and its answers vary): a beginning is finished by typing and quotes from that one message, the same
// request typed without the number is asked for it, and what the tool rows say. Screenshots:
// docs/screens/real-starters-<name>.png (light, phone).
//
// needs the real-model stack. usage: PORT_BASE=8920 node conformance/real-starters.mjs
import { mkdirSync } from "node:fs";
import { HOST, browser, cardIn, freshLedger, seen, settled, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Starters with a real model");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
await freshLedger();
const chromium = await browser();
const errors = [];

async function visit() {
  const context = await chromium.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  watchErrors(page, errors);
  await page.goto(`${HOST}/`);
  return { context, page };
}
const rowsOf = (page) => page.locator("tool-row").evaluateAll((rows) => rows.map((r) => `${r.querySelector('[data-slot="name"]').textContent} [${r.dataset.state}]`));
const cardShows = (page, text) => seen(cardIn(page).first().locator("body").getByText(text).first().waitFor({ timeout: 90000 }));

for (const [starter, finishing, shows, name] of [
  ["Buy ₦500 MTN airtime", "07031234567", "MTN airtime", "airtime"],
  ["Buy ₦1,000 MTN data", "07031234567", "MTN data", "data"],
  ["Send ₦5,000 to a friend", "0123456789 GTBank", "₦5,000", "transfer"],
]) {
  const { context, page } = await visit();
  await page.getByRole("button", { name: starter, exact: true }).click();
  await page.keyboard.type(finishing);
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  check(await cardShows(page, shows), `${name}: the model quotes from the beginning and what was typed (card shows ${shows})`);
  await settled(page, 90000);
  await page.waitForTimeout(500);
  const rows = await rowsOf(page);
  check(rows.length >= 1 && rows.every((r) => !r.endsWith("[failed]")), `${name}: tool rows ${JSON.stringify(rows)}, none failed`);
  await page.screenshot({ path: `${screens}real-starters-${name}.png` });
  await context.close();
}

{
  const { context, page } = await visit();
  await page.locator("#text").fill("Buy ₦500 MTN airtime");
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  await page.locator("assistant-text").first().waitFor({ timeout: 90000 });
  await settled(page, 90000);
  const rows = await rowsOf(page);
  check(rows.length === 0, `the same request typed without a number is asked for it: no tool row (${JSON.stringify(rows)}), the reply: ${(await page.locator("assistant-text").first().innerText()).slice(0, 80)}`);
  await page.screenshot({ path: `${screens}real-starters-asks.png` });
  await context.close();
}

const unexpected = errors.filter((e) => !/Failed to load resource/.test(e));
check(unexpected.length === 0, `no page errors or policy violations ${unexpected.join("; ")}`);
await chromium.close();
finish();
