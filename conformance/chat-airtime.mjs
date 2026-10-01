// SPDX-License-Identifier: AGPL-3.0-or-later
// Airtime in the real chat: a person types their own number, approves on the card, pays on the checkout page,
// and the card goes straight to a delivered receipt (never "Refund due") by the connector's webhook, with
// every relay call from the page blocked. The failure number reads clearly, and a number quoted on the wrong
// network is refused before anyone pays. Screenshots: docs/screens/chat-airtime-<state>-<scheme>.png.
//
// needs the stack. usage: node conformance/chat-airtime.mjs
import { fileURLToPath } from "node:url";
import { browser, cardIn, freshLedger, pause, seen, startChat, say, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Airtime in the chat");
const screens = fileURLToPath(new URL("../docs/screens/", import.meta.url));
await freshLedger();
const chromium = await browser();
const errors = [];

async function openCard(context, message) {
  const page = await context.newPage();
  watchErrors(page, errors);
  const chat = await startChat(page, message);
  const card = cardIn(page);
  await card.getByRole("checkbox").waitFor({ timeout: 20000 });
  return { page, card, chat };
}

async function approveAndPay(context, { page, card }, button = "Pay with a test card") {
  await card.getByRole("checkbox").check();
  const popup = context.waitForEvent("page", { timeout: 15000 });
  await card.getByRole("button", { name: /Approve/ }).click();
  const checkout = await popup;
  await card.getByRole("button", { name: /Open checkout/ }).waitFor({ timeout: 8000 });
  const calls = [];
  await page.route("**/call", (route) => { calls.push(route.request().url()); return route.abort(); });
  await pause(500);
  const who = (await checkout.locator("h1").innerText()).trim();
  await checkout.getByRole("button", { name: button }).click();
  return { checkout, calls, who };
}

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}: a real number, delivered`);
  const context = await chromium.newContext({ viewport: { width: 420, height: 820 }, colorScheme: scheme });
  const opened = await openCard(context, "Airtime ₦500 to 0703 123 4567 on MTN");
  const { page, card } = opened;
  const shown = (await card.locator("article").innerText()).replace(/\s+/g, " ");
  check(/MTN airtime/.test(shown) && shown.includes("0703 123 4567") && shown.includes("₦500"), `the approval card shows what the person typed (${shown.slice(0, 90)})`);
  check(!/Simulated/.test(shown), "the card itself carries no simulation label");
  check(await page.locator('[data-slot="test-box"]').innerText() === "Test", "the page has the Test box on top");
  check((await page.locator('[data-slot="simulation-note"]').innerText()).trim() === "This is a simulation", "and the simulation line under the composer");
  const { checkout, calls, who } = await approveAndPay(context, opened);
  check(who === "MTN airtime", `the checkout page names what is bought (${who})`);
  check(await seen(card.getByText("Airtime delivered").first().waitFor({ timeout: 10000 })), "the card goes to the delivered receipt");
  const done = (await card.locator("article").innerText()).replace(/\s+/g, " ");
  check(!/Refund/i.test(done) && !/did not deliver/i.test(done), `with no refund text (${done.slice(0, 120)})`);
  check(done.includes("0703 123 4567"), "the receipt keeps the number as typed");
  check(!done.includes("0801 111 1111"), "and no other number");
  await page.unroute("**/call");
  await page.screenshot({ path: `${screens}chat-airtime-delivered-${scheme}.png` });
  check(await seen(page.getByText("Card: Airtime delivered").first().waitFor({ timeout: 12000 })) || (await page.getByText(/Card:/).count()) > 0, "and the note to the model is recorded");
  await context.close();
}

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}: the number that fails`);
  const context = await chromium.newContext({ viewport: { width: 420, height: 820 }, colorScheme: scheme });
  const opened = await openCard(context, "Airtime ₦500 to 100000000000 on MTN");
  const { page, card } = opened;
  await approveAndPay(context, opened);
  check(await seen(card.getByText("Refund due").first().waitFor({ timeout: 10000 })), "a paid order that could not be delivered says Refund due");
  const text = (await card.locator("article").innerText()).replace(/\s+/g, " ");
  check(/did not deliver/i.test(text) && text.includes("₦500") && text.includes("MTN airtime"), `the reason, what and how much are on the card (${text.slice(0, 130)})`);
  check(!/Airtime delivered/.test(text), "and it is not a receipt");
  await page.screenshot({ path: `${screens}chat-airtime-refund-${scheme}.png` });
  await context.close();
}

console.log("\nthe wrong network");
{
  const context = await chromium.newContext({ viewport: { width: 420, height: 820 } });
  const page = await context.newPage();
  watchErrors(page, errors);
  await startChat(page, "Airtime ₦500 to 0703 123 4567 on Airtel");
  check(await seen(page.waitForFunction(() => /is a MTN number, not Airtel/.test(document.querySelector("chat-thread").innerText), null, { timeout: 20000 })), "a number quoted on the wrong network is refused with the network it belongs to");
  check((await page.locator("card-frame").count()) === 0, "and no card asks anyone to pay");
  await context.close();
}

const unexpected = errors.filter((e) => !/ERR_FAILED|Failed to load resource|Applying inline style/.test(e));
check(unexpected.length === 0, `no page errors or policy violations ${unexpected.join("; ")}`);
await chromium.close();
finish();
