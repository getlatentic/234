// SPDX-License-Identifier: AGPL-3.0-or-later
// The menu card's full screen in the real chat page, through the display-mode API of the official
// AppBridge: the host lists the modes in the initialize context, answers the request by filling the window
// with a fixed overlay (a bar with a visible Close control, the page behind it inert and locked, Tab kept
// inside, Escape closing), and gives back the focus, the scroll position and the frame's height on the way
// out. Also on a phone, and the card page's policy against the frame itself.
//
// needs the stack (tools/up.sh). usage: node conformance/chat-menu-fullscreen.mjs
import { mkdirSync } from "node:fs";
import { devices } from "playwright";
import { HOST, browser, cardIn, freshLedger, seen, settled, suite, watchErrors } from "./lib.mjs";
import { approvalFrame, askForTheMenu, menuFrame, pickAndReview, say } from "./menu-chat-lib.mjs";

const { check, finish } = suite("Menu card, full screen in the chat");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
await freshLedger();
const chromium = await browser();
const PHONE = { ...devices["iPhone 13"], defaultBrowserType: undefined };
delete PHONE.defaultBrowserType;

const box = (page, selector) => page.locator(selector).first().evaluate((el) => {
  const r = el.getBoundingClientRect();
  return { x: r.x, y: r.y, width: r.width, height: r.height };
});
const state = (page) => page.evaluate(() => ({
  fixed: getComputedStyle(document.querySelector("card-frame")).position === "fixed",
  locked: document.documentElement.style.overflow === "hidden",
  inert: document.querySelectorAll("[inert]").length,
  dialog: document.querySelector("card-frame")?.getAttribute("role") === "dialog",
  scroll: scrollY,
  frameHeight: document.querySelector("card-frame iframe").style.height,
  active: document.activeElement?.tagName,
}));
const expand = (page) => menuFrame(page).getByRole("button", { name: "Full screen", exact: true });
const leaveButton = (page) => menuFrame(page).getByRole("button", { name: "Exit full screen", exact: true });
const close = (page) => page.getByRole("button", { name: "Close full screen" });

async function longThread(page) {
  for (let n = 0; n < 4; n += 1) await say(page, "slow:40@0.005");
  await page.getByText("word39 END").last().waitFor({ timeout: 30000 });
  await settled(page);
}

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}`);
  const context = await chromium.newContext({ colorScheme: scheme, viewport: { width: 420, height: 900 } });
  const page = await context.newPage();
  const errors = watchErrors(page);
  await askForTheMenu(page);
  await longThread(page);
  const frame = menuFrame(page);
  check(await expand(page).isVisible(), "the menu card shows an expand control, because the host listed fullscreen");
  await frame.getByRole("button", { name: "Add Zobo, 500ml", exact: true }).click();
  await page.evaluate(() => scrollTo(0, 60));
  const before = await state(page);
  const inlineBox = await box(page, "card-frame iframe");
  check(before.scroll > 0 && !before.fixed && !before.locked && before.inert === 0, `the page is scrolled (${before.scroll}) and free before it opens`);
  await page.screenshot({ path: `${screens}chat-menu-${scheme}-3-inline.png` });

  await expand(page).click();
  await leaveButton(page).waitFor();
  const open = await state(page);
  const frameBox = await box(page, "card-frame");
  check(open.fixed && frameBox.x === 0 && frameBox.y === 0 && frameBox.width === 420 && frameBox.height === 900, `the card fills the window (${frameBox.width}x${frameBox.height})`);
  check(open.dialog && (await page.locator("card-frame").getAttribute("aria-modal")) === "true" && (await page.locator("card-frame").getAttribute("aria-label")) === "Menu", "it is a modal dialog named Menu");
  check(open.locked && open.scroll === before.scroll, `the page behind does not scroll (${before.scroll} then ${open.scroll})`);
  const closeBox = await close(page).boundingBox();
  check(closeBox && closeBox.height >= 44 && closeBox.x + closeBox.width <= 420 && closeBox.y >= 0, `a visible Close control, at least 44 px tall (${Math.round(closeBox.width)}x${Math.round(closeBox.height)})`);
  check(open.inert > 0 && (await page.locator("#text").evaluate((el) => Boolean(el.closest("[inert]")))), "the rest of the page is inert, the composer included");
  await page.locator("#text").focus().catch(() => undefined);
  check((await page.evaluate(() => document.activeElement?.id)) !== "text", "and cannot take focus");
  const order = await menuFrame(page).getByRole("button", { name: "Review order" }).boundingBox();
  const list = await menuFrame(page).locator('[data-slot="scroller"]').boundingBox();
  check(order.y + order.height <= 900 && order.y + order.height > 780 && list.height > 500, `Review order sits at the bottom of the window, the list has room (${Math.round(list.height)} px)`);
  check(await menuFrame(page).locator("html").evaluate((el) => el.dataset.mode === "fullscreen"), "the card was told the mode and drew itself for it");
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${screens}chat-menu-${scheme}-4-fullscreen.png` });

  let stuck = 0;
  for (let n = 0; n < 45; n += 1) {
    await page.keyboard.press("Tab");
    if (!(await page.evaluate(() => document.querySelector("card-frame").contains(document.activeElement)))) stuck += 1;
  }
  for (let n = 0; n < 6; n += 1) {
    await page.keyboard.press("Shift+Tab");
    if (!(await page.evaluate(() => document.querySelector("card-frame").contains(document.activeElement)))) stuck += 1;
  }
  check(stuck === 0, "Tab and Shift+Tab stay inside the card, round the whole cycle");

  await page.keyboard.press("Escape");
  await expand(page).waitFor();
  const leftByEscape = await state(page);
  check(!leftByEscape.fixed && !leftByEscape.locked && leftByEscape.inert === 0 && leftByEscape.scroll === before.scroll, "Escape closes it and gives the page back at the same scroll position");
  check(leftByEscape.active === "IFRAME", "with focus back on the frame that held it");
  const back = await box(page, "card-frame iframe");
  check(Math.abs(back.height - inlineBox.height) < 3 && back.width === inlineBox.width, `and the frame is its old size (${back.width}x${back.height})`);

  await expand(page).click();
  await leaveButton(page).waitFor();
  await close(page).focus();
  await page.keyboard.press("Escape");
  await expand(page).waitFor();
  check(!(await state(page)).fixed, "Escape closes it from the host's own Close control as well");
  await expand(page).click();
  await leaveButton(page).waitFor();
  await close(page).click();
  await expand(page).waitFor();
  const closed = await state(page);
  check(!closed.fixed && closed.inert === 0 && closed.scroll === before.scroll, "the Close button closes it");
  await expand(page).click();
  await leaveButton(page).click();
  await expand(page).waitFor();
  check(!(await state(page)).fixed, "and so does the card's own Exit full screen");
  check((await frame.getByRole("group", { name: "Zobo, 500ml", exact: true }).locator("output").innerText()) === "1", "the cart was kept through all of it");

  console.log("ordering from full screen");
  await expand(page).click();
  await leaveButton(page).waitFor();
  await pickAndReview(page, { names: ["Chapman, 500ml"] });
  await approvalFrame(page).getByRole("button", { name: /Approve/ }).waitFor({ timeout: 20000 });
  const ordered = await state(page);
  check(!ordered.fixed && ordered.inert === 0 && !ordered.locked, "an order placed in full screen leaves it, so the approval card is in view");
  check(await seen(menuFrame(page).getByText("Order ready to approve").waitFor({ timeout: 8000 })), "and the menu card reads Order ready to approve");

  console.log("the policy against the frame");
  const blocked = await cardIn(page).first().locator("body").evaluate(async () => {
    const out = {};
    try { await fetch("https://example.test/"); out.fetch = "allowed"; } catch { out.fetch = "blocked"; }
    const image = new Image();
    out.image = await new Promise((resolve) => { image.onload = () => resolve("allowed"); image.onerror = () => resolve("blocked"); image.src = "https://example.test/x.png"; });
    return out;
  });
  check(blocked.fetch === "blocked" && blocked.image === "blocked", `the frame cannot fetch or load an image from an origin the view did not declare (${JSON.stringify(blocked)})`);
  check(errors.filter((e) => !/Content Security Policy|Failed to load resource|ERR_/.test(e)).length === 0, `no page errors ${errors.filter((e) => !/Content Security Policy|Failed to load resource|ERR_/.test(e))}`);
  await context.close();

  console.log("on a phone");
  const phone = await chromium.newContext({ ...PHONE, colorScheme: scheme });
  const small = await phone.newPage();
  watchErrors(small, []);
  await askForTheMenu(small);
  const width = PHONE.viewport.width;
  const height = PHONE.viewport.height;
  await menuFrame(small).getByRole("button", { name: "Add Zobo, 500ml", exact: true }).click();
  await small.waitForTimeout(300);
  await small.screenshot({ path: `${screens}chat-menu-${scheme}-5-phone.png` });
  const inlineFits = await small.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
  check(inlineFits, "the page does not scroll sideways with the menu card in it");
  await expand(small).click();
  await leaveButton(small).waitFor();
  const phoneBox = await box(small, "card-frame");
  check(phoneBox.width === width && phoneBox.height === height, `full screen fills the phone (${phoneBox.width}x${phoneBox.height})`);
  const closeOnPhone = await close(small).boundingBox();
  const reviewOnPhone = await menuFrame(small).getByRole("button", { name: "Review order" }).boundingBox();
  check(closeOnPhone.y >= 0 && closeOnPhone.height >= 44 && closeOnPhone.x + closeOnPhone.width <= width, "the Close control is on the screen and can be touched");
  check(reviewOnPhone.y + reviewOnPhone.height <= height && reviewOnPhone.y > height / 2, "and Review order is on the screen too");
  check(await small.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "with nothing spilling sideways");
  await small.waitForTimeout(300);
  await small.screenshot({ path: `${screens}chat-menu-${scheme}-6-phone-fullscreen.png` });
  await close(small).tap();
  await expand(small).waitFor();
  check(!(await state(small)).fixed, "a tap on Close returns to the chat");
  await phone.close();
}

await chromium.close();
finish();
