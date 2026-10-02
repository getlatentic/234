// SPDX-License-Identifier: AGPL-3.0-or-later
// The chats list is a sidebar on a wide screen and a drawer on a narrow one. Wide: it is open from the first
// paint with the 234 wordmark and a close button, the page makes room for it, closing it leaves the 234 icon
// as the button that opens it, and the choice is remembered across a reload. Narrow: nothing is docked, the
// 234 icon opens a modal drawer with the same header, and Escape closes it. Needs a stack with sign-in
// (AUTH=1), where the chats list is offered to a visitor with no chats. usage: node conformance/chat-sidebar.mjs
import { browser, openHome, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Chats sidebar");
const chromium = await browser();
const errors = [];

const docked = (page) => page.locator("chat-sheet dialog").evaluate((el) => el.open && !el.matches(":modal"));
const iconButton = (page) => page.locator('[data-action="chats"]');
const roomLeft = (page) => page.locator("chat-thread").evaluate((el) => parseFloat(getComputedStyle(el).paddingLeft));

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}: wide`);
  const context = await chromium.newContext({ viewport: { width: 1400, height: 850 }, colorScheme: scheme });
  const page = await context.newPage();
  watchErrors(page, errors);
  await openHome(page);
  check(await docked(page), "the sidebar is open by default");
  check(!(await iconButton(page).isVisible()), "and the 234 icon button is not shown while it is");
  check((await page.locator("chat-sheet dialog a[aria-label='234']").isVisible()) && (await page.locator('chat-sheet [data-action="close"]').isVisible()), "it shows the 234 wordmark and a close button");
  check((await roomLeft(page)) === 320, `the page makes room for it (${await roomLeft(page)}px on the left)`);
  check(await page.evaluate(() => !document.querySelector("chat-sheet dialog").contains(document.activeElement)), "opening it does not take the keyboard");

  await page.locator('chat-sheet [data-action="close"]').click();
  await iconButton(page).waitFor();
  check(!(await docked(page)) && (await iconButton(page).isVisible()), "closing it leaves the 234 icon");
  check((await iconButton(page).locator("img").count()) === 1, "and the icon is the 234 mark");
  check((await roomLeft(page)) === 0, "the page takes the room back");
  await page.reload();
  await page.locator("chat-thread[data-me]").waitFor({ state: "attached" });
  check(!(await docked(page)) && (await iconButton(page).isVisible()), "a reload keeps it closed");

  await iconButton(page).click();
  check(await docked(page), "the icon opens it again, docked and not modal");
  await page.reload();
  await page.locator("chat-thread[data-me]").waitFor({ state: "attached" });
  check(await docked(page), "a reload keeps it open");

  await page.setViewportSize({ width: 600, height: 850 });
  await page.waitForTimeout(150);
  check(!(await docked(page)), "a window made narrow drops the dock");
  await context.close();
}

console.log("\nnarrow");
{
  const context = await chromium.newContext({ viewport: { width: 400, height: 800 } });
  const page = await context.newPage();
  watchErrors(page, errors);
  await openHome(page);
  check(!(await docked(page)) && (await iconButton(page).isVisible()), "on a phone nothing is docked and the 234 icon is shown");
  await iconButton(page).click();
  check(await page.locator("chat-sheet dialog").evaluate((el) => el.matches(":modal")), "the icon opens a modal drawer");
  check(await page.locator("chat-sheet dialog a[aria-label='234']").isVisible(), "with the 234 wordmark");
  await page.keyboard.press("Escape");
  check(!(await page.locator("chat-sheet dialog").evaluate((el) => el.open)), "Escape closes it");
  check(await page.evaluate(() => document.activeElement?.dataset.action === "chats"), "and the keyboard goes back to the icon");
  await context.close();
}

check(errors.length === 0, `no page errors ${errors}`);
await chromium.close();
finish();
