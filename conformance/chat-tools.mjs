// SPDX-License-Identifier: AGPL-3.0-or-later
// Tool rows: one quiet line each, closed until opened, a small word only when the call did not work. A call the
// connector refused that the model then recovered from (it asked the question, or called again and it worked) is
// a muted line with no red and no raw error until the row is opened; red is for a turn that ends refused with
// nothing after it. The raw arguments and the connector's words sit in a compact code block inside the open row,
// never wider than the column. The keyboard ring hugs the label, is drawn for the keyboard only (never after a
// press, never on load, in Chromium and WebKit) and is not clipped. The scripted model plays the model that calls
// the airtime tool with an empty number ("blank phone: ...", host/tests/scripted_intents.py).
// Screenshots: docs/screens/refused-after-<scheme>-<state>.png (the before shots are refused-before-*).
//
// needs the stack (tools/up.sh). usage: node conformance/chat-tools.mjs
import { mkdirSync } from "node:fs";
import { webkit } from "playwright";
import { HOST, browser, freshLedger, seen, settled, startChat, suite, tokenColor, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Tool rows");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
await freshLedger();
const chromium = await browser();
const errors = [];

const PHONE = { width: 390, height: 780 };
const QUESTION = "Which number should get the ₦500 MTN airtime?";
const rows = (page) => page.locator("tool-row");
const word = (row) => row.locator('[data-slot="status"]').innerText();
const colour = (row) => row.locator('[data-slot="status"]').evaluate((el) => getComputedStyle(el).color);
const snapshot = (page) => rows(page).evaluateAll((all) => all.map((r) => [r.dataset.state, r.querySelector('[data-slot="status"]').textContent, r.querySelector("details").open]));

async function chatWith(page, message, ready) {
  await startChat(page, message);
  await ready(page);
  await settled(page);
  await page.waitForTimeout(300);
}
const answered = (page) => seen(page.locator("assistant-text").first().waitFor({ timeout: 20000 }));
const called = (page, count) => page.waitForFunction((n) => document.querySelectorAll("tool-row").length >= n && !document.querySelector("chat-thread[data-working]"), count, { timeout: 25000 });

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}: refused, then the model asks for the number`);
  const context = await chromium.newContext({ viewport: PHONE, colorScheme: scheme, deviceScaleFactor: 2 });
  const page = await context.newPage();
  watchErrors(page, errors);
  await chatWith(page, "blank phone: Buy ₦500 MTN airtime", answered);
  const row = rows(page).first();
  check((await rows(page).count()) === 1 && (await page.locator("assistant-text").first().innerText()) === QUESTION, "one tool row, then the question");
  check((await row.locator("summary").innerText()).replace(/\s+/g, " ").trim() === "Create airtime quote refused", "the row is the tool's plain name and the small word refused");
  check((await row.getAttribute("data-state")) === "refused" && (await colour(row)) === (await tokenColor(page, "ink-3")), "the word is in the quiet ink: a recovered refusal is not red");
  check((await row.locator("details").evaluate((d) => d.open)) === false && (await page.locator("details[open]").count()) === 0, "it is closed, and nothing on the page is open");
  const onShow = await page.locator("[data-slot=thread]").innerText();
  check(!(await row.locator("pre").first().isVisible()) && !(await row.locator("pre").last().isVisible()) && !/Invalid arguments|"phone"|amount_kobo/.test(onShow), "the raw arguments and the connector's error are not on show");
  const box = await row.locator("summary").boundingBox();
  const label = await row.locator("summary > span").boundingBox();
  check(box.height >= 44 && label.height < 32, `one line: a ${Math.round(box.height)}px target around a ${Math.round(label.height)}px label`);
  const bad = await tokenColor(page, "bad");
  check(!(await page.locator("[data-slot=thread] [data-state=failed]").count()) && (await row.evaluate((r, red) => [r, ...r.querySelectorAll("*")].every((el) => getComputedStyle(el).color !== red), bad)), "nothing in the row is drawn in the failure colour");
  check(await page.evaluate(() => document.activeElement?.localName !== "summary"), "no row has focus on load");
  await page.screenshot({ path: `${screens}refused-after-${scheme}-1-collapsed.png` });

  const before = await snapshot(page);
  await page.reload();
  await settled(page);
  check(JSON.stringify(await snapshot(page)) === JSON.stringify(before), `a reload draws the same row as the live page (${JSON.stringify(before)})`);
  check(await page.evaluate(() => document.activeElement?.localName !== "summary" && getComputedStyle(document.querySelector(".focus-ring-target")).outlineStyle === "none"), "and no ring on load");

  await rows(page).first().locator("summary").click();
  check(await row.locator("details").evaluate((d) => d.open), "a press opens it");
  const ring = await row.locator(".focus-ring-target").evaluate((el) => getComputedStyle(el).outlineStyle);
  check(ring === "none", "and a mouse press leaves no ring on the label");
  const args = await row.locator('[data-slot="arguments"]').innerText();
  const result = await row.locator('[data-slot="result"]').innerText();
  check(/"phone": ""/.test(args) && /"amount_kobo": 50000/.test(args), "open, it shows the arguments as sent, the empty number included");
  check(/^Invalid arguments for create_airtime_quote: phone/.test(result), "and the connector's words");
  const geometry = await row.evaluate((r) => {
    const column = r.getBoundingClientRect();
    return [...r.querySelectorAll("pre")].map((pre) => ({ right: pre.getBoundingClientRect().right, scrolls: getComputedStyle(pre).overflowX, font: parseFloat(getComputedStyle(pre).fontSize), left: pre.getBoundingClientRect().left, columnRight: column.right, columnLeft: column.left }));
  });
  check(geometry.every((g) => g.right <= g.columnRight + 0.5 && g.left >= g.columnLeft - 0.5 && g.scrolls === "auto" && g.font <= 12), "each code block is inside the column, 12px or smaller, and scrolls sideways");
  await page.waitForTimeout(300);
  check(await row.locator("summary svg").evaluate((el) => getComputedStyle(el).rotate === "90deg"), "the chevron turns down while it is open");
  await page.screenshot({ path: `${screens}refused-after-${scheme}-2-opened.png` });

  await rows(page).first().locator("summary").click();
  await page.locator("body").click({ position: { x: 5, y: 400 } });
  await page.keyboard.press("Tab");
  for (let i = 0; i < 6 && !(await page.evaluate(() => document.activeElement?.localName === "summary")); i++) await page.keyboard.press("Tab");
  const focus = await row.locator(".focus-ring-target").evaluate((el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const outer = { left: rect.left - 4, right: rect.right + 4, top: rect.top - 4, bottom: rect.bottom + 4 };
    const clipped = [];
    for (let node = el.parentElement; node; node = node.parentElement) {
      const overflow = getComputedStyle(node).overflow;
      const box = node.getBoundingClientRect();
      if (overflow !== "visible" && (outer.left < box.left || outer.right > box.right || outer.top < box.top || outer.bottom > box.bottom)) clipped.push(node.localName);
    }
    return { style: style.outlineStyle, width: style.outlineWidth, colour: style.outlineColor, offset: style.outlineOffset, left: outer.left, right: outer.right, clipped, high: rect.height, wide: rect.width, column: el.closest("tool-row").getBoundingClientRect().width };
  });
  check(focus.style === "solid" && focus.width === "2px" && focus.offset === "2px" && focus.colour === (await tokenColor(page, "primary")), `keyboard focus draws the 2px ring with a 2px offset (${focus.colour})`);
  check(focus.clipped.length === 0 && focus.left >= 0 && focus.right <= PHONE.width, `and it is not clipped (from ${Math.round(focus.left)} to ${Math.round(focus.right)} of ${PHONE.width}px, clipping ancestors: ${focus.clipped.join(",") || "none"})`);
  check(focus.high < 32 && focus.wide < focus.column, `it hugs the label (${Math.round(focus.wide)} x ${Math.round(focus.high)}px), not the whole row`);
  await page.keyboard.press("Enter");
  check(await row.locator("details").evaluate((d) => d.open), "Enter opens it from the keyboard");
  await page.keyboard.press("Space");
  check((await row.locator("details").evaluate((d) => d.open)) === false, "and Space closes it");
  await page.keyboard.press("Space");
  await page.keyboard.press("Tab");
  const block = await row.locator('[data-slot="arguments"]').evaluate((el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const clipped = [];
    for (let node = el.parentElement; node; node = node.parentElement) {
      const box = node.getBoundingClientRect();
      if (getComputedStyle(node).overflow !== "visible" && (rect.left - 4 < box.left || rect.right + 4 > box.right || rect.top - 4 < box.top || rect.bottom + 4 > box.bottom)) clipped.push(node.localName);
    }
    return { focused: document.activeElement === el, style: style.outlineStyle, clipped, left: rect.left - 4, right: rect.right + 4 };
  });
  check(block.focused && block.style === "solid" && block.clipped.length === 0 && block.left >= 0 && block.right <= PHONE.width, `the scrollable code block can be reached by keyboard and its ring is not clipped (${block.clipped.join(",") || "no clipping ancestor"})`);
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Space");
  await page.screenshot({ path: `${screens}refused-after-${scheme}-3-keyboard-focus.png` });
  // A browser that calls focus after a press "keyboard focus" (the keyboard was the last input, or the engine treats
  // a click on a summary that way) must still draw nothing: the row noted the press.
  const pressed = await row.evaluate((r) => {
    const summary = r.querySelector("summary");
    summary.blur();
    summary.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    summary.focus();
    return { keyboardFocus: summary.matches(":focus-visible"), ring: getComputedStyle(r.querySelector(".focus-ring-target")).outlineStyle };
  });
  check(pressed.keyboardFocus && pressed.ring === "none", "focus that the browser calls keyboard focus, right after a press, still draws no ring");
  await page.keyboard.press("ArrowDown");
  check((await row.locator(".focus-ring-target").evaluate((el) => getComputedStyle(el).outlineStyle)) === "solid", "and the next key brings it back");
  await context.close();
}

console.log("\nrefused, then the model calls again and it works");
{
  const context = await chromium.newContext({ viewport: PHONE });
  const page = await context.newPage();
  watchErrors(page, errors);
  await chatWith(page, "blank phone: Buy ₦500 MTN airtime for 08031234567", (p) => called(p, 2));
  const all = rows(page);
  check((await all.count()) === 2, "two rows: the refusal and the call that worked");
  check((await word(all.nth(0))) === "refused" && (await colour(all.nth(0))) === (await tokenColor(page, "ink-3")), "the first says refused, quietly");
  check((await word(all.nth(1))) === "" && (await all.nth(1).getAttribute("data-state")) === "ok", "the second says nothing");
  check(!(await all.nth(1).locator('[data-slot="status"]').isVisible()), "and draws no empty space after its name");
  check((await page.locator("card-frame").count()) === 1 && (await page.locator("details[open]").count()) === 0, "the card is there and every row is closed");
  await context.close();
}

console.log("\nrefused, and nothing after it: the turn ended in a failure");
for (const scheme of ["light", "dark"]) {
  const context = await chromium.newContext({ viewport: PHONE, colorScheme: scheme, deviceScaleFactor: 2 });
  const page = await context.newPage();
  watchErrors(page, errors);
  await chatWith(page, "blank phone, silent: Buy ₦500 MTN airtime", (p) => called(p, 1));
  const row = rows(page).first();
  check((await word(row)) === "failed" && (await row.getAttribute("data-state")) === "failed", `${scheme}: the word is failed`);
  check((await colour(row)) === (await tokenColor(page, "bad")), `${scheme}: and it is the one red on the page`);
  check((await page.locator("assistant-text").count()) === 0 && (await row.locator("details").evaluate((d) => d.open)) === false, `${scheme}: no reply, and the row is still closed`);
  await page.screenshot({ path: `${screens}refused-after-${scheme}-4-failed.png` });
  await page.reload();
  await settled(page);
  check((await word(rows(page).first())) === "failed" && (await colour(rows(page).first())) === (await tokenColor(page, "bad")), `${scheme}: a reload draws it the same`);
  await context.close();
}

console.log("\na call that worked, and a long argument on a 320px phone");
{
  const context = await chromium.newContext({ viewport: { width: 320, height: 700 } });
  const page = await context.newPage();
  watchErrors(page, errors);
  const long = "x".repeat(130);
  await chatWith(page, `Pay ₦2,500 to Ada Stores for ${long}`, (p) => called(p, 1));
  const row = rows(page).first();
  check((await row.locator("summary").innerText()).trim() === "Create payment quote", "a call that worked is its name and no word");
  await row.locator("summary").click();
  const fit = await row.evaluate((r) => {
    const column = r.getBoundingClientRect();
    const pre = r.querySelector('[data-slot="arguments"]');
    return { scrolls: pre.scrollWidth > pre.clientWidth, right: pre.getBoundingClientRect().right, columnRight: column.right, page: document.documentElement.scrollWidth };
  });
  check(fit.scrolls && fit.right <= fit.columnRight + 0.5 && fit.page <= 320, "a 130-character argument scrolls inside its block: the block is no wider than the column and the page does not scroll sideways");
  await context.close();
}

console.log("\nWebKit: a press draws no ring, the keyboard does");
{
  const engine = await webkit.launch();
  const context = await engine.newContext({ viewport: PHONE });
  const page = await context.newPage();
  await startChat(page, "blank phone: Buy ₦500 MTN airtime");
  await page.locator("assistant-text").first().waitFor({ timeout: 20000 });
  await settled(page);
  const outline = () => page.locator(".focus-ring-target").first().evaluate((el) => getComputedStyle(el).outlineStyle);
  check((await outline()) === "none", "no ring on load");
  await page.locator("summary").first().click();
  check((await outline()) === "none" && (await page.locator("details").first().evaluate((d) => d.open)), "after a mouse press the row is open and has no ring");
  await page.locator("body").click({ position: { x: 5, y: 400 } });
  for (let i = 0; i < 6 && !(await page.evaluate(() => document.activeElement?.localName === "summary")); i++) await page.keyboard.press("Tab");
  check((await page.evaluate(() => document.activeElement?.localName)) === "summary" && (await outline()) === "solid", "after the keyboard reaches it the ring is drawn");
  await page.keyboard.press("Enter");
  check((await page.locator("details").first().evaluate((d) => d.open)) === false, "and Enter closes the row");
  await engine.close();
}

const unexpected = errors.filter((e) => !/Failed to load resource/.test(e));
check(unexpected.length === 0, `no page errors or policy violations ${unexpected.join("; ")}`);
await chromium.close();
finish();
