// SPDX-License-Identifier: AGPL-3.0-or-later
// The two lines that sit above the composer: "Reconnecting" while the stream is down and the error of a
// message that was refused. Each is one line out of the flow (the transcript does not move when it comes
// and goes), announced to a screen reader, and clear of the composer; "Reconnecting" goes away as soon as the
// stream is back, with or without new events.
//
// needs the stack (tools/up.sh). usage: node conformance/chat-states.mjs
import { mkdirSync } from "node:fs";
import { browser, HOST, openHome, pause, sendFirst, settled, suite, tokenColor, watchErrors } from "./lib.mjs";

const { check, finish } = suite("States above the composer");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
const chromium = await browser();
const errors = [];

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}`);
  const context = await chromium.newContext({ colorScheme: scheme, viewport: { width: 420, height: 700 } });
  const page = await context.newPage();
  watchErrors(page, errors);
  await openHome(page);
  await sendFirst(page, "echo: a reply to stay above");
  await settled(page);
  const offline = page.locator('[data-slot="offline"]');
  const error = page.locator('[data-slot="error"]');
  const place = () =>
    page.evaluate(() => {
      const last = [...document.querySelectorAll('[data-slot="thread"] > *')].at(-1).getBoundingClientRect();
      const pill = document.querySelector('[data-slot="pill"]').getBoundingClientRect();
      return { last: Math.round(last.top), pill: Math.round(pill.top), height: document.documentElement.scrollHeight };
    });
  // The composer slides down after the first message; measure once that, and anything else that ends, has ended.
  await page.evaluate(() => Promise.all(document.getAnimations().filter((a) => a.effect?.getComputedTiming().iterations !== Infinity).map((a) => a.finished.catch(() => {}))));
  const quiet = await place();
  check(!(await offline.isVisible()) && !(await error.isVisible()), "neither line is shown while all is well");

  await page.route("**/ticket*", (route) => route.abort());
  await page.evaluate(() => document.querySelector("chat-thread").stream.restart());
  await offline.waitFor({ timeout: 5000 });
  const down = await place();
  const box = await offline.boundingBox();
  check(down.last === quiet.last && down.pill === quiet.pill && down.height === quiet.height, "Reconnecting appears without moving the transcript or the composer");
  check(box.y + box.height <= down.pill && down.pill - (box.y + box.height) <= 16, `it sits on the line just above the composer (${Math.round(down.pill - (box.y + box.height))}px clear)`);
  check((await offline.getAttribute("role")) === "status" && (await offline.innerText()).trim() === "Reconnecting", "it is a status line that says one word");
  check((await offline.evaluate((el) => getComputedStyle(el).color)) === (await tokenColor(page, "ink-3")), "in the quiet ink, not an alarm colour");
  check((await page.locator('[data-slot="offline"] span').evaluate((el) => el.getAnimations().length)) === 1, "its dot pulses, the one motion that says something is being retried");
  await page.screenshot({ path: `${screens}states-${scheme}-1-reconnecting.png` });
  await page.unroute("**/ticket*");
  await offline.waitFor({ state: "hidden", timeout: 12000 });
  check(true, "and it goes away once the stream is back, though nothing new arrived");

  await page.locator("#text").fill("pay with 4242 4242 4242 4242");
  await page.keyboard.press("Enter");
  await error.waitFor({ timeout: 8000 });
  const failed = await place();
  const errorBox = await error.boundingBox();
  check(failed.last === quiet.last && failed.height === quiet.height, "an error appears without moving the transcript");
  check((await error.getAttribute("role")) === "alert" && errorBox.y + errorBox.height <= failed.pill, "it is an alert on the line above the composer");
  check((await error.evaluate((el) => getComputedStyle(el).color)) === (await tokenColor(page, "bad")), "in the failure colour");
  check((await page.locator("#text").inputValue()) === "pay with 4242 4242 4242 4242", "and the person's words are still in the field");
  await page.screenshot({ path: `${screens}states-${scheme}-2-error.png` });
  await page.locator("#text").fill("echo: fixed");
  await page.keyboard.press("Enter");
  await error.waitFor({ state: "hidden", timeout: 8000 });
  check(true, "sending again clears it");
  await pause(200);
  await context.close();
}

// The refused message answers 422 and the blocked ticket request fails on purpose: both are logged by the browser.
const unexpected = errors.filter((e) => !/Failed to load resource/.test(e));
check(unexpected.length === 0, `no page errors or policy violations ${unexpected.join("; ")}`);
await chromium.close();
finish();
