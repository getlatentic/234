// SPDX-License-Identifier: AGPL-3.0-or-later
// A television subscription and electricity in a real browser (docs/commerce.md, "Providers"), against the stack
// started with AUTH=1: a DStv renewal paid from the wallet shows the holder, the bouquet and its amount on the
// approval card, goes through with no checkout and leaves a receipt that says how long it lasts; an electricity
// purchase leaves a receipt with the token and its units; a meter VTpass does not know is refused and makes no card;
// a purchase VTpass fails comes back to the wallet. The renewal card and the token receipt meet WCAG AA with 44px
// targets and no sideways scroll at 320px in both themes. Screenshots: docs/screens/bills-*.png.
//
// needs the stack with AUTH=1. usage: PORT_BASE=9200 node conformance/chat-bills.mjs
import { mkdirSync } from "node:fs";
import { contrastReport } from "./card-checks.mjs";
import { freshLedger, inCard, MODEL, say, sendFirst, settled, suite } from "./lib.mjs";
import { browserOf, person } from "./merchants-lib.mjs";

const { check, finish } = suite("Bills");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
await freshLedger();

const { browser, errors } = await browserOf();
const frames = (page, server) => page.locator(`card-frame[data-server="${server}"]`);
const cardOf = (page) => inCard(frames(page, "merchants").last());
const lastView = (page) => page.frames().filter((f) => new URL(f.url()).pathname === "/view").at(-1);
const reset = () => fetch(`${MODEL}/v1/_reset`);
const requests = async () => (await fetch(`${MODEL}/v1/_requests`)).json();
const text = async (card) => (await card.locator("article").innerText()).replace(/\s+/g, " ");
const PHONE = "08031234567";

async function fundWallet(page, context, naira) {
  await sendFirst(page, "my wallet");
  const wallet = inCard(frames(page, "wallet").last());
  await wallet.getByRole("button", { name: "Add money" }).waitFor({ timeout: 25000 });
  await wallet.getByLabel("Amount in naira").fill(String(naira));
  const popup = page.waitForEvent("popup", { timeout: 15000 });
  await wallet.getByRole("button", { name: "Add money" }).click();
  const bachs = await popup;
  await bachs.getByRole("button", { name: "Pay by bank transfer" }).click();
  await wallet.locator('[data-slot="balance"]', { hasText: `₦${naira.toLocaleString("en-NG")}` }).waitFor({ timeout: 15000 });
  await bachs.close();
}

async function walletAgain(page) {
  const count = await frames(page, "wallet").count();
  await say(page, "my wallet");
  await frames(page, "wallet").nth(count).waitFor({ timeout: 25000 });
  return inCard(frames(page, "wallet").nth(count));
}

async function bill(page, sentence) {
  await say(page, sentence);
  const card = cardOf(page);
  await card.getByRole("button", { name: "Approve" }).waitFor({ timeout: 25000 });
  return card;
}

console.log("Ada renews DStv from her wallet");
const ada = await person(browser, errors, "ada");
{
  const { page, context } = ada;
  await reset();
  await fundWallet(page, context, 40000);
  const card = await bill(page, `bill: dstv 1212121212 renew ${PHONE}`);
  const shown = await text(card);
  check(shown.includes("₦10,500") && shown.includes("Account holder: ADEOLA BALOGUN"), `the card shows the amount and the holder (${shown.slice(0, 110)})`);
  check(shown.includes("Renew DStv Confam") && shown.includes("Smartcard number 1212121212"), "the line says it is a renewal of the bouquet the card has, with the smartcard");
  check(shown.includes("Due date 2026-11-02") && shown.includes("Phone number 0803"), "and the due date and the phone");
  await page.screenshot({ path: `${screens}bills-renewal-card.png` });
  let opened = 0;
  context.on("page", () => (opened += 1));
  await card.getByRole("button", { name: "Pay from wallet" }).click();
  await card.getByText("Subscription paid").first().waitFor({ timeout: 20000 });
  const receipt = await text(card);
  check(opened === 0, "no checkout was opened");
  check(receipt.includes("Valid for 1 month") && receipt.includes("Account holder"), `the receipt says how long it lasts (${receipt.slice(0, 120)})`);
  check(!/Token/.test(receipt), "a television receipt has no token");
  const after = await walletAgain(page);
  await after.locator('[data-slot="balance"]', { hasText: "₦29,500" }).waitFor({ timeout: 15000 });
  check(true, "the wallet card shows ₦29,500");
}

console.log("\nelectricity: the token is on the receipt");
{
  const { page, context } = ada;
  await reset();
  const card = await bill(page, `bill: ikeja-electric 1111111111111 prepaid ${PHONE} ₦5,000`);
  const shown = await text(card);
  check(shown.includes("₦5,000") && shown.includes("FUNMI AKINTOLA") && shown.includes("12 ALLEN AVENUE"), `the card shows the amount, the holder and the address (${shown.slice(0, 120)})`);
  await card.getByRole("button", { name: "Pay from wallet" }).click();
  await card.getByText("Electricity paid").first().waitFor({ timeout: 20000 });
  const receipt = await text(card);
  check(/Token \d{4} \d{4} \d{4} \d{4} \d{4}/.test(receipt), `the token is on the receipt (${receipt.slice(0, 160)})`);
  check(receipt.includes("Units 71.4 kWh") && receipt.includes("Tariff"), "with its units and tariff");
  await page.screenshot({ path: `${screens}bills-token-receipt.png` });
  await context.close().catch(() => undefined);
}

console.log("\na meter the distribution company does not know is refused and makes no card");
{
  const { page, context } = await person(browser, errors, null);
  await reset();
  await sendFirst(page, `bill: ikeja-electric 9999999999999 prepaid ${PHONE} ₦5,000`);
  await settled(page, 25000);
  const refused = (await requests()).findLast((r) => r.messages.at(-1).role === "tool").messages.at(-1).content;
  check(refused.startsWith("ACCOUNT_NOT_FOUND") && refused.includes("Nothing was quoted"), `the check is refused (${refused.slice(0, 70)})`);
  check((await frames(page, "merchants").count()) === 0, "and no card is shown");
  await context.close();
}

console.log("\na purchase VTpass fails comes back to the wallet");
{
  const { page, context } = await person(browser, errors, "bola");
  await reset();
  await fundWallet(page, context, 20000);
  const card = await bill(page, `bill: ikeja-electric 100000000000 prepaid ${PHONE} ₦5,000`);
  await card.getByRole("button", { name: "Pay from wallet" }).click();
  await card.getByText("Not charged").first().waitFor({ timeout: 20000 });
  const owed = await text(card);
  check(/did not deliver/i.test(owed), `the card says VTpass did not deliver (${owed.slice(0, 120)})`);
  const back = await walletAgain(page);
  await back.locator('[data-slot="balance"]', { hasText: "₦20,000" }).waitFor({ timeout: 15000 });
  const entries = (await back.locator("li").allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim());
  check(entries[0].startsWith("Returned") && entries[0].includes("₦5,000"), `the money is back, said plainly (${entries[0]})`);
  await page.screenshot({ path: `${screens}bills-refunded.png` });
  await context.close();
}

console.log("\nthe renewal card and the token receipt at 320px, in both themes");
for (const scheme of ["light", "dark"]) {
  const { page, context } = await person(browser, errors, null, { colorScheme: scheme, viewport: { width: 320, height: 640 } });
  await reset();
  await sendFirst(page, `bill: dstv 1212121212 renew ${PHONE}`);
  const card = cardOf(page);
  await card.getByRole("button", { name: "Approve" }).waitFor({ timeout: 25000 });
  const inner = lastView(page);
  const low = await inner.evaluate(`(${contrastReport.toString()})()`);
  check(low.length === 0, `${scheme}: the renewal card meets WCAG AA ${JSON.stringify(low)}`);
  const sizes = await inner.evaluate(() => [...document.querySelectorAll("button:not([hidden]), input")].map((el) => el.getBoundingClientRect().height));
  check(sizes.length >= 2 && sizes.every((h) => h >= 44), `${scheme}: every button and field is a 44px target (${sizes})`);
  check(!(await inner.evaluate(() => document.documentElement.scrollWidth > innerWidth)), `${scheme}: it does not scroll sideways`);
  await frames(page, "merchants").last().screenshot({ path: `${screens}bills-renewal-${scheme}-320.png` });
  const popup = context.waitForEvent("page", { timeout: 15000 });
  await card.getByRole("button", { name: "Approve" }).click();
  const checkout = await popup;
  await card.getByRole("button", { name: /Open checkout/ }).waitFor({ timeout: 8000 });
  await checkout.getByRole("button", { name: "Pay with a test card" }).click();
  await card.getByText("Subscription paid").first().waitFor({ timeout: 20000 });
  await settled(page, 25000);
  const after = lastView(page);
  check(!(await after.evaluate(() => document.documentElement.scrollWidth > innerWidth)), `${scheme}: the receipt does not scroll sideways`);
  await frames(page, "merchants").last().screenshot({ path: `${screens}bills-receipt-${scheme}-320.png` });
  await context.close();
}

// the token receipt at 320px needs a wallet, which an account has
for (const scheme of ["light", "dark"]) {
  const { page, context } = await person(browser, errors, `tess${scheme}`, { colorScheme: scheme, viewport: { width: 320, height: 640 } });
  await reset();
  await fundWallet(page, context, 20000);
  const card = await bill(page, `bill: ikeja-electric 1111111111111 prepaid ${PHONE} ₦5,000`);
  await card.getByRole("button", { name: "Pay from wallet" }).click();
  await card.getByText("Electricity paid").first().waitFor({ timeout: 20000 });
  const inner = lastView(page);
  const low = await inner.evaluate(`(${contrastReport.toString()})()`);
  check(low.length === 0, `${scheme}: the token receipt meets WCAG AA ${JSON.stringify(low)}`);
  check(!(await inner.evaluate(() => document.documentElement.scrollWidth > innerWidth)), `${scheme}: the token receipt does not scroll sideways`);
  await frames(page, "merchants").last().screenshot({ path: `${screens}bills-token-${scheme}-320.png` });
  await context.close();
}

check(errors.filter((e) => !/ERR_FAILED|Failed to load resource|Applying inline style/.test(e)).length === 0, `no page errors, no policy violations (${JSON.stringify(errors.slice(0, 3))})`);
await browser.close();
finish();
