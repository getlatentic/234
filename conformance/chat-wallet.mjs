// SPDX-License-Identifier: AGPL-3.0-or-later
// The wallet in a real browser against the stack started with AUTH=1: a visitor has none and is offered no wallet
// tool; a signed-in person opens the wallet card, adds money on the simulated Bachs page and sees the balance
// arrive; the airtime card offers "Pay from wallet" only while the wallet covers the quote, pays from it with no
// checkout, and the wallet card shows the balance go down. Accessibility (contrast, 44px targets, no sideways
// scroll) is checked at 320px in both themes. Screenshots: docs/screens/wallet-*.png.
//
// The sign-in is the host's own endpoint with a token from the Firebase Auth emulator (as chat-memory.mjs).
// needs the stack with AUTH=1. usage: PORT_BASE=9200 node conformance/chat-wallet.mjs
import { mkdirSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { chromium } from "playwright";
import { contrastReport } from "./card-checks.mjs";
import { csrfOf, freshLedger, HOST, inCard, MODEL, openHome, say, sendFirst, settled, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("The wallet");
const base = Number(process.env.PORT_BASE ?? 8900);
const EMULATOR = `127.0.0.1:${base + 7}`;
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
await freshLedger();

const browser = await chromium.launch({
  args: ["--host-resolver-rules=MAP fonts.googleapis.com ~NOTFOUND, MAP fonts.gstatic.com ~NOTFOUND, MAP unpkg.com ~NOTFOUND"],
});
const errors = [];
const run = randomBytes(3).toString("hex");

async function emulatorToken(email) {
  const identity = JSON.stringify({ sub: `uid-${email}`, email, email_verified: true });
  const form = new URLSearchParams({ id_token: identity, providerId: "google.com" }).toString();
  const reply = await fetch(`http://${EMULATOR}/identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key=fake-api-key-for-the-emulator`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ postBody: form, requestUri: "http://localhost", returnIdpCredential: true, returnSecureToken: true }),
  });
  return (await reply.json()).idToken;
}

/** A browser of its own for a person; `who` signs them in as that account, none leaves a visitor. */
async function person(who, options = {}) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, ...options });
  const page = await context.newPage();
  watchErrors(page, errors);
  await openHome(page);
  if (who) {
    const csrf = await csrfOf(page);
    const signed = await context.request.post(`${HOST}/auth/session`, { data: { idToken: await emulatorToken(`${who}.${run}@example.com`) }, headers: { "X-CSRFToken": csrf } });
    if (signed.status() !== 200) throw new Error(`sign-in refused: ${signed.status()}`);
    await openHome(page);
  }
  return { context, page };
}

const walletFrames = (page) => page.locator('card-frame[data-server="wallet"]');
const walletCard = (page) => inCard(walletFrames(page).last());
const approvalCard = (page) => inCard(page.locator('card-frame[data-server="airtime"]').last());
const lastView = (page) => page.frames().filter((f) => new URL(f.url()).pathname === "/view").at(-1);
const reset = () => fetch(`${MODEL}/v1/_reset`);
const requests = async () => (await fetch(`${MODEL}/v1/_requests`)).json();
const sentFor = async (text) => (await requests()).findLast((r) => r.messages.at(-1).content === text);
const lastReply = async (page) => {
  await settled(page, 25000);
  return (await page.locator("assistant-text").last().innerText()).trim();
};
const balanceOf = async (card) => (await card.locator('[data-slot="balance"]').innerText()).trim();
const entriesOf = async (card) => (await card.locator("li").allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim());

async function openWallet(page, first = false) {
  const count = await walletFrames(page).count();
  await (first ? sendFirst(page, "my wallet") : say(page, "my wallet"));
  await walletFrames(page).nth(count).waitFor({ timeout: 25000 });
  const card = walletCard(page);
  await card.getByRole("button", { name: "Add money" }).waitFor({ timeout: 15000 });
  return card;
}

async function addMoney(page, card, naira) {
  await card.getByLabel("Amount in naira").fill(String(naira));
  const popup = page.waitForEvent("popup", { timeout: 15000 });
  await card.getByRole("button", { name: "Add money" }).click();
  const bachs = await popup;
  await bachs.waitForLoadState();
  return bachs;
}

console.log("a visitor has no wallet");
{
  const { page, context } = await person(null);
  await reset();
  await sendFirst(page, "my wallet");
  await page.locator("assistant-text").last().waitFor({ timeout: 25000 });
  check((await lastReply(page)).includes("sign in") && (await walletFrames(page).count()) === 0, "asked for the wallet, the assistant says to sign in and no card appears");
  const tools = (await sentFor("my wallet")).tools.map((t) => t.function.name);
  check(!tools.some((name) => name.startsWith("wallet__")), "the model was offered no wallet tool");
  await context.close();
}

console.log("\nAda adds money on the Bachs page and sees it arrive");
const ada = await person("ada");
{
  const { page } = ada;
  await reset();
  const card = await openWallet(page, true);
  check((await balanceOf(card)) === "₦0" && (await entriesOf(card)).length === 0, "a new wallet holds ₦0 and lists nothing");
  check((await lastReply(page)) === "Your wallet holds ₦0.", "the assistant reads the balance back in one line");
  check((await sentFor("my wallet")).tools.some((t) => t.function.name === "wallet__wallet_balance"), "the model is offered the wallet tool");
  const bachs = await addMoney(page, card, 5000);
  check(new URL(bachs.url()).pathname.startsWith("/sim/bachs/"), `Add money opens the Bachs checkout (${new URL(bachs.url()).pathname})`);
  check((await card.getByRole("button", { name: "Pay ₦5,000" }).count()) === 1, "the card keeps a button to reopen the payment");
  check((await bachs.locator("body").innerText()).includes("₦5,000"), "the checkout is for the amount typed");
  await bachs.getByRole("button", { name: "Pay by bank transfer" }).click();
  await bachs.getByText("Paid").waitFor({ timeout: 10000 });
  await card.locator('[data-slot="balance"]', { hasText: "₦5,000" }).waitFor({ timeout: 15000 });
  check(true, "the card shows ₦5,000 once Bachs' webhook has credited it");
  check(JSON.stringify(await entriesOf(card)) === JSON.stringify(["Added +₦5,000"]), `in plain words (${await entriesOf(card)})`);
  check((await card.getByRole("button", { name: /^Pay / }).count()) === 0, "and the payment button is gone");
  await bachs.close();
  await page.screenshot({ path: `${screens}wallet-added-chat.png` });
}

console.log("\nthe airtime card offers the wallet and pays from it");
{
  const { page, context } = ada;
  await reset();
  await say(page, "Airtime ₦500 to 0703 123 4567 on MTN");
  const card = approvalCard(page);
  await card.getByRole("button", { name: "Approve" }).waitFor({ timeout: 25000 });
  const pay = card.getByRole("button", { name: "Pay from wallet" });
  await pay.waitFor({ timeout: 10000 });
  check(true, "the approval card offers 'Pay from wallet' beside Approve, without the balance");
  await page.screenshot({ path: `${screens}wallet-airtime-offer-chat.png` });
  let opened = 0;
  context.on("page", () => (opened += 1));
  await pay.click();
  await card.getByText("Airtime delivered").first().waitFor({ timeout: 20000 });
  check(opened === 0, "the airtime is delivered with no checkout opened");
  const wallet = await openWallet(page);
  await wallet.locator('[data-slot="balance"]', { hasText: "₦4,500" }).waitFor({ timeout: 10000 });
  check(true, "the wallet card now shows ₦4,500");
  check((await entriesOf(wallet))[0] === "Paid airtime -₦500", `its newest entry says what was paid (${(await entriesOf(wallet))[0]})`);
}

console.log("\na quote the wallet does not cover is not offered it");
{
  const { page } = ada;
  await reset();
  await say(page, "Airtime ₦6000 to 0703 123 4567 on MTN");
  const card = approvalCard(page);
  await card.getByRole("button", { name: "Approve" }).waitFor({ timeout: 25000 });
  await page.waitForTimeout(1500);
  check((await card.getByRole("button", { name: /Pay from wallet/ }).count()) === 0, "₦6,000 against ₦4,500: Approve and the checkout only");
  await card.getByRole("button", { name: "Decline" }).click();
  await ada.context.close();
}

console.log("\nthe wallet card and the offer at 320px, in both themes");
for (const scheme of ["light", "dark"]) {
  const { page, context } = await person(`grace-${scheme}`, { colorScheme: scheme, viewport: { width: 320, height: 640 } });
  await reset();
  const card = await openWallet(page, true);
  const bachs = await addMoney(page, card, 2000);
  await bachs.getByRole("button", { name: "Pay by bank transfer" }).click();
  await card.locator('[data-slot="balance"]', { hasText: "₦2,000" }).waitFor({ timeout: 15000 });
  await bachs.close();
  const inner = lastView(page);
  const low = await inner.evaluate(`(${contrastReport.toString()})()`);
  check(low.length === 0, `${scheme}: the wallet card meets WCAG AA ${JSON.stringify(low)}`);
  const sizes = await inner.evaluate(() => [...document.querySelectorAll("button:not([hidden]), input")].map((el) => el.getBoundingClientRect().height));
  check(sizes.length >= 2 && sizes.every((h) => h >= 44), `${scheme}: the amount and Add money are 44px targets (${sizes})`);
  const wide = await inner.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  check(!wide, `${scheme}: nothing in the card scrolls sideways at 320px`);
  await walletFrames(page).last().screenshot({ path: `${screens}wallet-card-${scheme}-320.png` });
  await say(page, "Airtime ₦500 to 0703 123 4567 on MTN");
  const approval = approvalCard(page);
  await approval.getByRole("button", { name: "Pay from wallet" }).waitFor({ timeout: 25000 });
  const lowOffer = await lastView(page).evaluate(`(${contrastReport.toString()})()`);
  check(lowOffer.length === 0, `${scheme}: the approval card with the wallet offer meets WCAG AA ${JSON.stringify(lowOffer)}`);
  await page.locator('card-frame[data-server="airtime"]').last().screenshot({ path: `${screens}wallet-airtime-offer-${scheme}-320.png` });
  await context.close();
}

check(errors.length === 0, `no page errors, no policy violations (${JSON.stringify(errors.slice(0, 3))})`);
await browser.close();
finish();
