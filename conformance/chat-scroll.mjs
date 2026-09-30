// SPDX-License-Identifier: AGPL-3.0-or-later
// How the page follows a reply: it sticks to the newest line while a reply streams, stops when the person
// scrolls up (and stays where they put it however much more arrives), offers one "Latest" button that goes
// back and follows again, keeps the last line clear of the docked composer, and moves only where motion
// explains something (the drawer sliding in, the button going down) and not at all under reduced motion.
//
// needs the stack (tools/up.sh). usage: node conformance/chat-scroll.mjs
import { HOST, browser, pause, say, seen, settled, sendFirst, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Scroll");
const chromium = await browser();
const errors = [];

const distance = (page) => page.evaluate(() => document.documentElement.scrollHeight - scrollY - innerHeight);
const height = (page) => page.evaluate(() => document.documentElement.scrollHeight);
const latest = (page) => page.getByRole("button", { name: "Latest", exact: true });
const visible = (page) => latest(page).isVisible();
const dragUp = async (page, pixels) => {
  await page.mouse.move(210, 300);
  await page.mouse.wheel(0, -pixels);
  await pause(250);
};

console.log("a reply that streams");
{
  const context = await chromium.newContext({ viewport: { width: 420, height: 700 } });
  const page = await context.newPage();
  watchErrors(page, errors);
  await page.goto(`${HOST}/`);
  check((await page.locator('[data-slot="latest"]').count()) === 1 && !(await visible(page)), "the Latest button exists and is not shown on the empty home");
  await sendFirst(page, "slow:600@0.03");
  await page.waitForFunction(() => document.documentElement.scrollHeight > innerHeight + 200, null, { timeout: 30000 });
  await pause(500);
  const first = { d: await distance(page), h: await height(page) };
  await pause(1500);
  const second = { d: await distance(page), h: await height(page) };
  check(second.h > first.h + 20 && first.d <= 60 && second.d <= 60, `it follows the newest line as the page grows (${first.h} to ${second.h}px tall, ${first.d} and ${second.d}px from the end)`);
  check(!(await visible(page)), "and there is no Latest button while it follows");

  await dragUp(page, 500);
  const held = await page.evaluate(() => scrollY);
  await pause(1600);
  const later = { y: await page.evaluate(() => scrollY), h: await height(page), d: await distance(page) };
  check(Math.abs(later.y - held) <= 2 && later.d > 300, `scrolling up stops it: the page stays where the person put it while more arrives (moved ${later.y - held}px, ${later.d}px above the end)`);
  check(await visible(page), "the Latest button appears");
  check((await latest(page).evaluate((el) => el.getBoundingClientRect().height)) >= 44, "and is a 44px target");
  await page.screenshot({ path: new URL("../docs/screens/scroll-1-away.png", import.meta.url).pathname });

  await latest(page).click();
  await pause(900);
  check((await distance(page)) <= 4 && !(await visible(page)), "Latest goes to the end and goes away");
  await pause(1200);
  check((await distance(page)) <= 60, `and following starts again (${await distance(page)}px from the end after more words)`);
  await settled(page, 30000);
  await pause(300);
  const gap = await page.evaluate(() => {
    const last = [...document.querySelectorAll("assistant-text")].at(-1).getBoundingClientRect();
    return document.querySelector('[data-slot="pill"]').getBoundingClientRect().top - last.bottom;
  });
  check(gap >= 32, `at the end the last line sits above the composer's fade, not under it (${Math.round(gap)}px clear)`);

  console.log("\na person who scrolled up and then sends");
  await page.evaluate(() => scrollTo(0, 0));
  await pause(300);
  check(await visible(page), "scrolling to the top shows Latest, with nothing streaming");
  await say(page, "echo: back at the bottom");
  await seen(page.locator("assistant-text", { hasText: "back at the bottom" }).waitFor());
  await pause(500);
  check((await distance(page)) <= 60 && !(await visible(page)), "sending a message goes to the end");

  console.log("\nthe drawer");
  await page.getByRole("button", { name: "Chats" }).click();
  await page.locator("chat-sheet dialog[open]").waitFor();
  const names = await page.locator("chat-sheet dialog").evaluate((el) => el.getAnimations().map((a) => a.animationName));
  check(names.includes("drawer-in"), `it slides in (${names})`);
  await page.keyboard.press("Escape");
  await context.close();
}

console.log("\nreduced motion");
{
  const context = await chromium.newContext({ viewport: { width: 420, height: 700 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  watchErrors(page, errors);
  await page.goto(`${HOST}/`);
  await sendFirst(page, "slow:500@0.005");
  await settled(page, 30000);
  await page.evaluate(() => scrollTo(0, 0));
  await pause(300);
  await latest(page).click();
  await pause(60);
  check((await distance(page)) <= 2, "Latest goes to the end at once, without a glide");
  await page.getByRole("button", { name: "Chats" }).click();
  await page.locator("chat-sheet dialog[open]").waitFor();
  const names = await page.locator("chat-sheet dialog").evaluate((el) => [el, ...el.querySelectorAll("*")].flatMap((n) => n.getAnimations()).map((a) => a.animationName));
  check(names.length === 0, `the drawer does not slide (${names})`);
  await page.keyboard.press("Escape");
  const running = await page.evaluate(() => document.getAnimations().map((a) => a.animationName ?? a.constructor.name));
  check(running.length === 0, `nothing on the page is animating (${running})`);
  await context.close();
}

check(errors.length === 0, `no page errors or policy violations ${errors.join("; ")}`);
await chromium.close();
finish();
