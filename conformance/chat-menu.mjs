// SPDX-License-Identifier: AGPL-3.0-or-later
// The menu card in the real chat, end to end with the scripted model: asking for the menu gives a card and
// no table in the thread; the card's order opens an approval card of its own in the transcript, without the
// model being asked and without the approval token reaching it; the same cards in the same order after a
// reload and in a second tab; the menu card still works after a reload until its order exists.
//
// needs the stack (tools/up.sh). usage: node conformance/chat-menu.mjs
import { mkdirSync } from "node:fs";
import { HOST, browser, cardFrames, freshLedger, modelRequests, seen, suite, watchErrors } from "./lib.mjs";
import { approvalFrame, askForTheMenu, cardCount, menuFrame, pickAndReview, say, threadText } from "./menu-chat-lib.mjs";

const { check, finish } = suite("Menu card in the chat");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
await freshLedger();
const chromium = await browser();
const PRICE_OR_TABLE = /₦|\|.*\|/;
const ITEM_NAMES = ["Jollof", "Zobo", "Beef suya", "Chapman", "Puff puff", "Egusi"];

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}`);
  await fetch(`${process.env.MODEL_URL ?? `http://127.0.0.1:${Number(process.env.PORT_BASE ?? 8900) + 2}`}/v1/_reset`);
  const context = await chromium.newContext({ colorScheme: scheme, viewport: { width: 420, height: 900 } });
  const page = await context.newPage();
  const errors = watchErrors(page);
  const chat = await askForTheMenu(page);
  const menu = menuFrame(page);

  console.log("asking for the menu");
  check(await page.locator("summary", { hasText: "Search menu" }).count() === 1, "a tool row shows Search menu");
  check((await page.locator("card-frame").getAttribute("data-uri")) === "ui://food-order/menu.html", "the card is the menu view of the food connector");
  check((await page.frameLocator("card-frame iframe").locator("iframe").getAttribute("sandbox")) === "allow-scripts", 'its frame is sandbox="allow-scripts" and nothing else');
  check((await menu.locator("li[data-item]").count()) === 11, "the card lists the eleven items");
  const words = await threadText(page);
  check(!PRICE_OR_TABLE.test(words) && !ITEM_NAMES.some((n) => words.includes(n)), "the conversation itself holds no price, no table and no item name");
  check(words.includes("Pick what you like on the card."), "the model's reply is one short line");
  const sent = (await modelRequests()).filter((r) => r.tools);
  const afterSearch = JSON.stringify(sent.at(-1).messages);
  check(!ITEM_NAMES.some((n) => afterSearch.includes(n)) && !afterSearch.includes("₦") && !afterSearch.includes("card_id"), "the model was sent no item, price or card id: only that it may not list them");
  check(afterSearch.includes("do not list the items or prices"), "and was told the card shows them");
  const served = await (await page.request.get(`${HOST}/c/${chat}/card?server=food-order&uri=ui://food-order/menu.html`)).json();
  check(Object.keys(served.csp).length === 0 && served.hosts.length === 0, "the menu card declares no origin to load from, so it is shown with the restrictive default and no notice");
  const viewAddress = cardFrames(page)[0].url();
  const proxyPolicy = (await page.request.get(viewAddress)).headers()["content-security-policy"];
  check(proxyPolicy.includes("img-src 'self' data:;") && proxyPolicy.includes("connect-src 'self';"), "and its view's policy is the specification's default: images from the sandbox and data:, no other connection");
  await menu.getByRole("button", { name: "Add Zobo, 500ml", exact: true }).click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${screens}chat-menu-${scheme}-1-menu.png` });

  console.log("the menu card after a reload, before any order");
  const second = await context.newPage();
  watchErrors(second, errors);
  await second.goto(`${HOST}/c/${chat}/`);
  await menuFrame(second).getByRole("searchbox").waitFor({ timeout: 15000 });
  check((await cardCount(second, "Menu")) === 1 && (await cardCount(second, "Approval")) === 0, "a second tab shows the menu card and no approval card yet");
  await menuFrame(second).getByRole("searchbox").fill("moi moi");
  check((await menuFrame(second).locator("li[data-item]").count()) === 1, "and it is a working menu: search finds Moi moi");
  await page.reload();
  await menu.getByRole("searchbox").waitFor({ timeout: 15000 });
  await menu.getByRole("button", { name: "Add Zobo, 500ml", exact: true }).click();
  check((await menu.getByRole("button", { name: "Review order" }).isEnabled()), "after a reload the menu card takes items and Review order is ready");

  console.log("ordering");
  await pickAndReview(page);
  await approvalFrame(page).getByRole("button", { name: /Approve/ }).waitFor({ timeout: 20000 });
  check((await cardCount(page, "Approval")) === 1, "an approval card appears in the transcript");
  const order = await page.locator("card-frame").evaluateAll((els) => els.map((el) => el.dataset.uri));
  check(JSON.stringify(order) === JSON.stringify(["ui://food-order/menu.html", "ui://food-order/card.html"]), "after the menu card, in the order things happened");
  check(await seen(menu.getByText("Order ready to approve").waitFor({ timeout: 8000 })), "the menu card says Order ready to approve, in one line");
  check((await menu.getByRole("button").count()) === 0, "and has no button left");
  const approval = approvalFrame(page);
  const shown = await approval.locator("body").innerText();
  check(shown.includes("Mama Put Yaba") && shown.includes("Surulere") && shown.includes("₦"), `the approval card shows the server's own quote (${shown.replace(/\s+/g, " ").slice(0, 90)}...)`);
  check(await seen(page.getByText("Card: Order ready to approve").waitFor({ timeout: 8000 })), 'the transcript notes it in one short row: "Card: Order ready to approve"');
  check((await page.locator("chat-thread:not([data-working])").count()) === 1, "no turn was started for it");
  check(await seen(menuFrame(second).getByText("Order ready to approve").waitFor({ timeout: 8000 })) && (await cardCount(second, "Approval")) === 1, "the second tab shows the order and the approval card without a reload");
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${screens}chat-menu-${scheme}-2-ordered.png` });

  console.log("what the model is and is not told");
  await say(page, "thanks");
  await page.getByText("I can't do that").waitFor({ timeout: 20000 });
  const after = JSON.stringify((await modelRequests()).filter((r) => r.tools).at(-1).messages);
  check(after.includes("[card update] The person's menu made quote qt-") && after.includes("get_quote_status"), "the next request carries a note that a quote was made, and how to report on it");
  check(!after.includes("approvalToken") && !/\b[0-9a-f]{64}\b/.test(after), "no approval token in anything the model was sent");
  check(!ITEM_NAMES.some((n) => after.includes(n)), "still no item name");

  console.log("reload, and the same conversation elsewhere");
  await page.reload();
  await approval.getByRole("button", { name: /Approve/ }).waitFor({ timeout: 15000 });
  const reloaded = await page.locator("card-frame").evaluateAll((els) => els.map((el) => el.dataset.uri));
  check(JSON.stringify(reloaded) === JSON.stringify(order), "after a reload the same two cards are there, in the same order");
  check(await seen(menuFrame(page).getByText("Order ready to approve").waitFor({ timeout: 8000 })) && (await menuFrame(page).getByRole("button").count()) === 0, "the menu card comes back as Order ready to approve, not as a menu");
  const third = await context.newPage();
  watchErrors(third, errors);
  await third.goto(`${HOST}/c/${chat}/`);
  await approvalFrame(third).getByRole("button", { name: /Approve/ }).waitFor({ timeout: 15000 });
  check(JSON.stringify(await third.locator("card-frame").evaluateAll((els) => els.map((el) => el.dataset.uri))) === JSON.stringify(order) && (await third.locator("summary", { hasText: "Search menu" }).count()) === 1, "a tab opened now shows them too");

  console.log("the approval card is a real one");
  const popup = context.waitForEvent("page", { timeout: 15000 });
  await approval.getByRole("button", { name: /Approve/ }).click();
  const checkout = await popup.then((p) => p, () => null);
  check(Boolean(checkout) && checkout.url().includes("/sim/checkout/qt-"), "Approve on it opens the Paystack checkout");
  await checkout?.close();

  const unexpected = errors.filter((e) => !/Failed to load resource/.test(e));
  check(unexpected.length === 0, `no page errors or policy violations ${unexpected.join("; ")}`);
  await context.close();
}

await chromium.close();
finish();
