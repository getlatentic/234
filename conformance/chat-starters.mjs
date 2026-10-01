// SPDX-License-Identifier: AGPL-3.0-or-later
// The starters that need something only the person knows ("Buy ₦500 MTN airtime for ", "Send ₦5,000 to "): a
// press puts the beginning in the composer with the cursor after it and focuses it, sends nothing, leaves the
// starters where they are, and the message goes (once) when the person finishes it and sends. Complete starters
// send on one press (chat-home.mjs). Keyboard and touch are covered, and the model that is asked for an airtime
// top-up without a number asks for it.
// Screenshots: docs/screens/starters-<scheme>-<state>.png.
//
// needs the stack (tools/up.sh). usage: node conformance/chat-starters.mjs
import { mkdirSync } from "node:fs";
import { browser, cardIn, freshLedger, HOST, openHome, seen, settled, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Starters that need the person");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
await freshLedger();
const chromium = await browser();
const errors = [];

const fills = (page) => page.locator("chat-starters button[data-fill]");
const visit = async (options = {}) => {
  const context = await chromium.newContext({ viewport: { width: 390, height: 780 }, ...options });
  const page = await context.newPage();
  watchErrors(page, errors);
  const posts = [];
  page.on("request", (request) => request.method() === "POST" && /\/(start|send)$/.test(request.url()) && posts.push(request.postDataJSON()));
  await openHome(page);
  return { context, page, posts };
};
const field = (page) => page.evaluate(() => {
  const el = document.querySelector("#text");
  return { value: el.value, focused: document.activeElement === el, start: el.selectionStart, end: el.selectionEnd };
});
const cardShows = (page, text) => seen(cardIn(page).first().locator("body").getByText(text).first().waitFor({ timeout: 25000 }));

console.log("the three that need the person are marked, the others are not");
{
  const { context, page } = await visit();
  const marked = await page.locator("chat-starters button").evaluateAll((buttons) => buttons.map((b) => [b.textContent.trim(), b.hasAttribute("data-fill"), b.dataset.text]));
  check(JSON.stringify(marked.filter(([, fill]) => fill).map(([label]) => label)) === JSON.stringify(["Buy ₦500 MTN airtime", "Buy ₦1,000 MTN data", "Send ₦5,000 to a friend"]), "airtime, data and the transfer are beginnings");
  check(marked.filter(([, fill]) => !fill).every(([label, , text]) => label === text), "food, paying a merchant and the help question are whole messages");
  await context.close();
}

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}: a press fills the field and waits`);
  const { context, page, posts } = await visit({ colorScheme: scheme });
  await page.getByRole("button", { name: "Buy ₦500 MTN airtime", exact: true }).click();
  await page.waitForTimeout(400);
  let f = await field(page);
  check(f.value === "Buy ₦500 MTN airtime for " && f.focused && f.start === f.value.length && f.end === f.value.length, `the field holds "${f.value}", has focus and the cursor is at the end`);
  check(posts.length === 0 && (await page.locator("chat-thread[data-draft]").count()) === 1, "nothing was sent and the page is still the empty home");
  check((await fills(page).count()) === 3 && (await page.locator("chat-starters button:disabled").count()) === 0 && (await page.locator("chat-starters").isVisible()), "the starters are all still there and usable");
  await page.screenshot({ path: `${screens}starters-${scheme}-1-filled.png` });

  await page.getByRole("button", { name: "Send ₦5,000 to a friend", exact: true }).click();
  f = await field(page);
  check(f.value === "Send ₦5,000 to " && f.focused && f.start === f.value.length, "another beginning replaces the first in the same field, cursor at the end");
  await page.getByRole("button", { name: "Buy ₦1,000 MTN data", exact: true }).click();
  await page.keyboard.type("08031234567");
  f = await field(page);
  check(f.value === "Buy ₦1,000 MTN data for 08031234567", `what the person types lands after the beginning (${f.value})`);
  check(posts.length === 0 && (await page.locator("chat-starters").isVisible()), "still nothing sent, starters still there, while they type");
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  check(posts.length === 1 && posts[0].text === "Buy ₦1,000 MTN data for 08031234567", "Enter sends one message, the beginning and the number");
  check(!(await page.locator("chat-starters").isVisible()), "and only now do the starters go");
  check(await cardShows(page, "MTN data"), "the model quotes the top-up from that one message: the approval card shows it");
  await settled(page);
  await context.close();
}

console.log("\nairtime and the transfer, finished and sent");
{
  const { context, page, posts } = await visit();
  await page.getByRole("button", { name: "Buy ₦500 MTN airtime", exact: true }).click();
  await page.keyboard.type("0703 123 4567".replaceAll(" ", ""));
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  check(posts.length === 1 && posts[0].text === "Buy ₦500 MTN airtime for 07031234567", "the round button sends it as well");
  check(await cardShows(page, "MTN airtime"), "airtime: the approval card shows the number's top-up");
  await context.close();
}
{
  const { context, page } = await visit();
  await page.getByRole("button", { name: "Send ₦5,000 to a friend", exact: true }).click();
  await page.keyboard.type("0000000000 Zenith");
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  check(await cardShows(page, "₦5,000"), "transfer: the approval card shows the amount");
  await context.close();
}

console.log("\nthe keyboard");
{
  const { context, page, posts } = await visit();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  const f = await field(page);
  check(f.value === "Buy ₦500 MTN airtime for " && f.focused && f.start === f.value.length, "Tab to the first starter and Enter fills the field and moves focus into it");
  check(posts.length === 0, "and sends nothing");
  await context.close();
}

console.log("\na phone with a touch screen");
{
  const { context, page, posts } = await visit({ hasTouch: true, isMobile: true });
  check(await page.evaluate(() => matchMedia("(pointer: coarse)").matches), "the pointer is coarse");
  await page.getByRole("button", { name: "Buy ₦500 MTN airtime", exact: true }).tap();
  const f = await field(page);
  check(f.focused && f.value === "Buy ₦500 MTN airtime for " && f.start === f.value.length, "a tap on a beginning focuses the field: the person is about to type");
  check(posts.length === 0, "and sends nothing");
  await context.close();
}
{
  const { context, page, posts } = await visit({ hasTouch: true, isMobile: true });
  await page.getByRole("button", { name: "What can you do?", exact: true }).tap();
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  check(posts.length === 1 && !(await field(page)).focused, "a tap on a whole message sends it and leaves the keyboard down");
  await context.close();
}

console.log("\nthe model, asked for airtime without a number");
{
  const { context, page, posts } = await visit();
  await page.locator("#text").fill("Buy ₦500 MTN airtime");
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  check(await seen(page.locator("assistant-text", { hasText: "Which number should get the ₦500 MTN airtime?" }).first().waitFor({ timeout: 20000 })), "it asks for the number and calls no tool");
  await settled(page);
  check((await page.locator("tool-row").count()) === 0 && posts.length === 1, "no tool row, one message");
  await context.close();
}

const unexpected = errors.filter((e) => !/Failed to load resource/.test(e));
check(unexpected.length === 0, `no page errors or policy violations ${unexpected.join("; ")}`);
await chromium.close();
finish();
