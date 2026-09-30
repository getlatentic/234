// SPDX-License-Identifier: AGPL-3.0-or-later
// Contrast and names, a card 320 px wide, and a menu of hundreds of items.
import { contrastReport } from "../card-checks.mjs";
import { controls as c, refusal, spawned } from "./harness.mjs";

const LONG = "Fried rice, dodo, grilled chicken, peppered snail and a very long extra side of moi moi";

export const longNames = (h) =>
  h.withMenu({ items: h.items.map((item, i) => (i % 3 === 0 ? { ...item, name: `${LONG} (${item.name})` } : item)) });

export const bigMenu = (h, count) =>
  h.withMenu({
    items: Array.from({ length: count }, (_, n) => {
      const base = h.items[n % h.items.length];
      return { ...base, item_id: `item-${n}`, name: `${base.name} ${n + 1}`, available: base.available || n % 5 !== 0 };
    }),
  });

async function contrastOf(h, check, scheme, name, options, prepare) {
  const { page, context, errors, frame } = await h.open({ scheme, ...options });
  await prepare?.({ page, frame });
  const low = await frame.locator("body").evaluate(`(${contrastReport.toString()})()`);
  check(low.length === 0 && errors.length === 0, `${name}: text passes WCAG AA${low.length ? ` ${JSON.stringify(low.slice(0, 3))}` : ""}${errors.length ? ` ${errors}` : ""}`);
  const unnamed = await frame.locator("button, select, input").evaluateAll((els) => els.filter((el) => !(el.getAttribute("aria-label") || el.labels?.[0]?.textContent || el.textContent).trim()).length);
  check(unnamed === 0, `${name}: every control has an accessible name`);
  await context.close();
}

export async function contrastAndNames(h, check, scheme) {
  console.log(`\n${scheme}: contrast and names`);
  const inCart = ({ frame }) => frame.locator('[data-slot="add"]:not([hidden])').first().click();
  await contrastOf(h, check, scheme, "menu", {}, null);
  await contrastOf(h, check, scheme, "with items in the cart", {}, inCart);
  await contrastOf(h, check, scheme, "long names", { result: longNames(h) }, inCart);
  await contrastOf(h, check, scheme, "no match", {}, ({ frame }) => c.search(frame).fill("zzz"));
  await contrastOf(h, check, scheme, "full screen", { hostContext: { availableDisplayModes: ["inline", "fullscreen"] } }, ({ frame }) => frame.getByRole("button", { name: "Full screen", exact: true }).click());
  await contrastOf(h, check, scheme, "a refusal", { answer: refusal("ITEM_UNAVAILABLE: Sold out.") }, async ({ frame }) => {
    await inCart({ frame });
    await c.review(frame).click();
    await frame.getByRole("alert").waitFor();
  });
  await contrastOf(h, check, scheme, "ready", { answer: spawned() }, async ({ frame }) => {
    await inCart({ frame });
    await c.review(frame).click();
    await frame.getByText("Order ready to approve").waitFor();
  });
}

export async function narrowCard(h, check, scheme) {
  console.log(`\n${scheme}: a card 320 px wide`);
  const { page, context, frame } = await h.open({ scheme, width: 320, result: longNames(h), hostContext: { availableDisplayModes: ["inline", "fullscreen"] } });
  check(await frame.locator("html").evaluate((el) => el.scrollWidth <= el.clientWidth), "nothing overflows sideways");
  const row = c.rows(frame).first();
  await row.locator('[data-slot="add"]').click();
  const targets = {
    add: c.rows(frame).nth(1).locator('[data-slot="add"]'), less: row.locator('[data-slot="less"]'), more: row.locator('[data-slot="more"]'),
    search: c.search(frame), fullscreen: frame.getByRole("button", { name: "Full screen", exact: true }), chip: frame.getByRole("button", { name: "Soups" }),
    area: c.area(frame), clear: frame.getByRole("button", { name: "Clear" }), review: c.review(frame),
  };
  const sizes = Object.fromEntries(await Promise.all(Object.entries(targets).map(async ([name, t]) => [name, await t.boundingBox()])));
  const small = Object.entries(sizes).filter(([, b]) => !b || b.width < 43.9 || b.height < 43.9).map(([name, b]) => `${name} ${b && `${Math.round(b.width)}x${Math.round(b.height)}`}`);
  check(small.length === 0, `every control is at least 44 px each way at 320 px${small.length ? ` (too small: ${small})` : ""}`);
  const name = row.locator('[data-slot="name"]');
  check(await name.evaluate((el) => el.getBoundingClientRect().height > parseFloat(getComputedStyle(el).lineHeight) * 2.5), "a long name wraps over several lines");
  const chipsScroll = await frame.getByRole("group", { name: "Category" }).evaluate((el) => el.scrollWidth > el.clientWidth);
  check(chipsScroll, "the chips scroll sideways on their one row");
  await h.shot(page, "narrow", scheme);
  await context.close();
}

export async function bigList(h, check, scheme) {
  console.log(`\n${scheme}: 300 items`);
  const menu = bigMenu(h, 300);
  const { page, context, frame } = await h.open({ scheme, result: menu });
  const height = await page.evaluate(() => window.__height);
  check(height < 720, `the card stays ${height} px tall`);
  const rendered = await c.rows(frame).count();
  check(rendered <= 40, `only the first chunk of rows is built (${rendered} of 300)`);
  const scroller = frame.locator('[data-slot="scroller"]');
  check(await scroller.evaluate((el) => el.scrollHeight > el.clientHeight * 2), "the list scrolls inside the card");
  await c.add(frame, "Jollof rice with fried chicken 1").click();
  await scroller.evaluate((el) => el.scrollTo(0, el.scrollHeight));
  await page.waitForTimeout(400);
  check((await c.rows(frame).count()) > rendered, "scrolling to the end brings the next chunk");
  const box = await c.review(frame).boundingBox();
  const inside = await page.locator("#card").boundingBox();
  check(box.y >= inside.y && box.y + box.height <= inside.y + inside.height, "Review order stays in view with the list scrolled to its end");
  for (let n = 0; n < 12; n += 1) await scroller.evaluate((el) => el.scrollTo(0, el.scrollHeight)).then(() => page.waitForTimeout(120));
  check((await c.rows(frame).count()) === 300, "the whole menu can be reached by scrolling");
  await scroller.evaluate((el) => el.scrollTo(0, 0));

  const timings = await frame.locator("body").evaluate(async () => {
    const box = document.querySelector('[data-slot="search"]');
    const out = [];
    for (const text of ["j", "jo", "jol", "jollof", "jollof rice", "zobo", "", "chapman", "q", ""]) {
      const start = performance.now();
      box.value = text;
      box.dispatchEvent(new Event("input", { bubbles: true }));
      await new Promise((resolve) => requestAnimationFrame(resolve));
      out.push(performance.now() - start);
    }
    return out;
  });
  const slowest = Math.max(...timings);
  check(slowest < 120, `a keystroke filters and redraws 300 items in ${Math.round(slowest)} ms at worst`);
  await c.search(frame).fill("Zobo, 500ml 251");
  check((await c.rows(frame).count()) === 1, "an item far down the menu is found by search");
  await c.search(frame).fill("Jollof");
  for (let n = 0; n < 14; n += 1) {
    const add = frame.locator('[data-slot="add"]:not([hidden]):not(:disabled)').first();
    if (!(await add.count())) break;
    await add.click();
  }
  const picked = await frame.locator('[data-slot="stepper"]:not([hidden])').count();
  check(picked === 12, `at most 12 different items can be picked, and the 13th Add is disabled (${picked})`);
  await c.search(frame).fill("");
  await h.shot(page, "tall", scheme);
  await context.close();
}
