// SPDX-License-Identifier: AGPL-3.0-or-later
// Rows, drawings, Add and the stepper, the cart summary, Clear, search and the category chips.
import { controls as c, naira } from "./harness.mjs";

export async function rowsAndCart(h, check, scheme) {
  console.log(`\n${scheme}: rows, Add, stepper, cart`);
  const [first, second] = h.available;
  const { page, context, errors, frame } = await h.open({ scheme });
  check((await c.rows(frame).count()) === h.items.length, `one row for each of the ${h.items.length} items`);
  check((await frame.locator('li[data-item] svg use[href^="#art-"]').count()) === h.items.length, "each row has its own drawing, since the simulated merchant has no photos");
  const kinds = await frame.locator("li[data-item] use").evaluateAll((els) => [...new Set(els.map((el) => el.getAttribute("href")))]);
  check(kinds.length === 7, `seven kinds of drawing are used (${kinds.map((k) => k.slice(5))})`);
  const tints = await frame.locator('li[data-item] [data-slot="tile"]').evaluateAll((els) => new Set(els.map((el) => getComputedStyle(el).backgroundColor)).size);
  check(tints === 4, `the tiles carry four tints, one for each family (${tints})`);
  check((await frame.getByText(first.note).count()) === 1 && (await frame.getByText(naira(first.price_kobo), { exact: true }).count()) >= 1, "a row shows its name, its note and its price in naira");
  const sold = h.items.filter((i) => !i.available);
  check((await frame.locator('[data-slot="sold-out"]:not([hidden])').count()) === sold.length && (await c.add(frame, sold[0].name).count()) === 0, "a sold-out item says so and has no Add button");
  check(await c.review(frame).isDisabled(), "Review order is disabled while the cart is empty");
  check((await c.summary(frame)) === "0 items ₦0", `an empty cart reads "0 items ₦0" (${await c.summary(frame)})`);
  check((await frame.getByRole("heading").count()) === 0, "there are no headings");
  await h.shot(page, "empty", scheme);

  await c.add(frame, first.name).click();
  check((await c.add(frame, first.name).isHidden()) && (await c.quantity(frame, first.name).innerText()) === "1", "Add turns into a stepper showing 1");
  check(await c.more(frame, first.name).evaluate((el) => el === el.getRootNode().activeElement), "and focus moves to its plus button");
  check((await c.summary(frame)).startsWith(`1 item ${naira(first.price_kobo + h.fee)}`), `the summary counts the item and totals it with delivery (${await c.summary(frame)})`);
  check(await c.review(frame).isEnabled(), "Review order is enabled once something is in the cart");
  await c.more(frame, first.name).click();
  await c.add(frame, second.name).click();
  const sum = 2 * first.price_kobo + second.price_kobo + h.fee;
  check((await c.total(frame).innerText()) === naira(sum) && (await c.summary(frame)).startsWith("3 items"), `two of one and one of another: 3 items, ${naira(sum)}`);
  check((await frame.getByText(`incl. ${naira(h.fee)} delivery`).count()) === 1, "the delivery fee is named once, beside the total");
  await c.less(frame, first.name).click();
  await c.less(frame, first.name).click();
  check((await c.add(frame, first.name).isVisible()) && (await c.add(frame, first.name).evaluate((el) => el === el.getRootNode().activeElement)), "minus down to zero brings Add back, with focus");
  check((await c.total(frame).innerText()) === naira(second.price_kobo + h.fee), "the total follows the minus button");
  await c.add(frame, first.name).click();
  for (let n = 0; n < 12; n += 1) if (await c.more(frame, first.name).isEnabled()) await c.more(frame, first.name).click();
  check((await c.quantity(frame, first.name).innerText()) === "10" && (await c.more(frame, first.name).isDisabled()), "the plus button stops at ten of one item");
  check(await c.less(frame, first.name).evaluate((el) => el === el.getRootNode().activeElement), "and focus moves to the minus button rather than being lost");
  await frame.getByRole("button", { name: "Clear" }).click();
  check((await c.summary(frame)) === "0 items ₦0" && (await c.review(frame).isDisabled()) && (await c.add(frame, first.name).isVisible()), "Clear empties the cart");
  check(await c.search(frame).evaluate((el) => el === el.getRootNode().activeElement), "and puts focus in the search field");
  check((await frame.getByRole("button", { name: "Clear" }).count()) === 0 || (await frame.getByRole("button", { name: "Clear" }).isHidden()), "Clear is gone when there is nothing to clear");
  check(errors.length === 0, `no page errors or policy violations ${errors}`);
  await context.close();
}

export async function searchAndChips(h, check, scheme) {
  console.log(`\n${scheme}: search and categories`);
  const { page, context, frame } = await h.open({ scheme });
  const visibleNames = () => c.rows(frame).evaluateAll((els) => els.map((el) => el.querySelector('[data-slot="name"]').textContent));
  const search = c.search(frame);
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  const typed = async (text) => {
    await search.fill(text);
    return visibleNames();
  };
  check((await typed("moi moi")).join() === "Moi moi, 2 wraps", 'searching "moi moi" finds Moi moi, 2 wraps');
  check((await typed("MOIMOI")).length === 1, 'the case and the space do not matter ("MOIMOI")');
  check((await typed("egúsí")).join() === "Egusi soup with pounded yam", 'accents are ignored ("egúsí" finds Egusi)');
  check((await typed("gbegiri")).length === 1, "notes are searched too (gbegiri)");
  check((await typed("sweet dough")).join() === "Puff puff, 6 pieces", "every word must match, in any order");
  check((await typed("drinks")).length === 3, "a category name finds its items");
  const networkBefore = (await h.calls(page)).length;
  await typed("zzz");
  check((await frame.getByRole("status").filter({ hasText: "No match" }).isVisible()) && (await c.rows(frame).count()) === 0, 'an empty result is one short line: "No match"');
  await h.shot(page, "no-match", scheme);
  check((await typed("")).length === h.items.length, "clearing the field brings the whole menu back");
  check((await h.calls(page)).length === networkBefore && networkBefore === 0 && requests.length === 0, "searching calls no tool and makes no request");

  const chips = frame.getByRole("group", { name: "Category" }).getByRole("button");
  check((await chips.allInnerTexts()).join() === "All,Mains,Soups,Sides,Drinks", "the categories the menu has become chips, after All");
  const oneRow = await frame.getByRole("group", { name: "Category" }).evaluate((el) => new Set([...el.children].map((chip) => chip.offsetTop)).size === 1);
  check(oneRow, "the chips sit on one row");
  await frame.getByRole("button", { name: "Drinks", exact: true }).click();
  check((await visibleNames()).length === 3 && (await frame.getByRole("button", { name: "Drinks", exact: true }).getAttribute("aria-pressed")) === "true", "a chip shows only its category and is pressed");
  await search.fill("zobo");
  check((await visibleNames()).join() === "Zobo, 500ml", "a chip and a search work together");
  await frame.getByRole("button", { name: "All", exact: true }).click();
  await search.fill("");
  check((await visibleNames()).length === h.items.length, "All shows every item");
  const one = h.withMenu({ items: h.items.map((i) => ({ ...i, category: "mains" })) });
  const alone = await h.open({ scheme, result: one });
  check((await alone.frame.getByRole("group", { name: "Category" }).count()) === 0 || (await alone.frame.getByRole("group", { name: "Category" }).getByRole("button").count()) === 0, "a menu with one category has no chips");
  await alone.context.close();
  await context.close();
}
