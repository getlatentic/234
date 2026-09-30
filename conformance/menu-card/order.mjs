// SPDX-License-Identifier: AGPL-3.0-or-later
// What Review order sends and what the card shows after the server answers, and the keyboard.
import { controls as c, refusal, spawned } from "./harness.mjs";

export async function ordering(h, check, scheme) {
  console.log(`\n${scheme}: the order`);
  const [first, second] = h.available;
  {
    const { page, context, frame } = await h.open({ scheme, answer: spawned() });
    await c.add(frame, first.name).click();
    await c.more(frame, first.name).click();
    await c.add(frame, second.name).click();
    await c.area(frame).selectOption("Lekki Phase 1");
    await h.shot(page, "picked", scheme);
    await c.review(frame).click();
    await frame.getByText("Order ready to approve").waitFor({ timeout: 5000 });
    const sent = await h.calls(page);
    check(sent.length === 1 && sent[0].name === "order_from_menu", "Review order makes one order_from_menu call");
    const expected = { card_id: h.menu.structuredContent.card_id, items: [{ item_id: first.item_id, quantity: 2 }, { item_id: second.item_id, quantity: 1 }], delivery_area: "Lekki Phase 1" };
    check(JSON.stringify(sent[0].args) === JSON.stringify(expected), `it sends the card id, item ids, quantities and the area only (${JSON.stringify(sent[0]?.args)})`);
    check(!JSON.stringify(sent).match(/kobo|price|total|₦/i), "no price or total travels with it");
    check((await frame.getByRole("button").count()) === 0, "the card then shows one line and no button");
    check((await frame.getByRole("status").innerText()).trim() === "Order ready to approve", "that line says Order ready to approve");
    await h.shot(page, "ready", scheme);
    await context.close();
  }
  {
    const { page, context, frame } = await h.open({ scheme, answer: refusal("ITEM_UNAVAILABLE: Amala, ewedu and gbegiri is sold out. Pick another item from the menu.") });
    await c.add(frame, first.name).click();
    await c.review(frame).click();
    const alert = frame.getByRole("alert").filter({ hasText: "Amala" });
    await alert.waitFor({ timeout: 5000 });
    check(!(await alert.innerText()).includes("ITEM_UNAVAILABLE"), "a refusal shows as one alert without its code");
    check((await c.quantity(frame, first.name).innerText()) === "1" && (await c.review(frame).isEnabled()), "the cart is kept and the person can try again");
    await h.shot(page, "refused", scheme);
    await context.close();
  }
  {
    const { page, context, frame } = await h.open({ scheme });
    await c.add(frame, first.name).click();
    await page.evaluate((r) => window.__bridge.sendToolResult(r), spawned());
    await frame.getByText("Order ready to approve").waitFor({ timeout: 5000 });
    await page.evaluate((r) => window.__bridge.sendToolResult(r), h.menu);
    await page.waitForTimeout(200);
    check((await frame.getByText("Order ready to approve").count()) === 1 && (await frame.getByRole("button").count()) === 0, "a state the host pushes (another tab ordered, or a reload) shows the same line, and a menu after it does not bring the buttons back");
    await context.close();
  }
  {
    const { page, context, frame } = await h.open({ scheme, answer: spawned(), hostContext: { availableDisplayModes: ["inline", "fullscreen"] } });
    await c.add(frame, first.name).click();
    await frame.getByRole("button", { name: "Full screen", exact: true }).click();
    await frame.getByRole("button", { name: "Exit full screen", exact: true }).waitFor();
    await c.review(frame).click();
    await frame.getByText("Order ready to approve").waitFor({ timeout: 5000 });
    check((await page.evaluate(() => window.__log.filter((e) => e.kind === "displaymode").map((e) => e.mode))).join() === "fullscreen,inline", "an order placed in full screen leaves it, so the approval card can be seen");
    await context.close();
  }
}

export async function keyboard(h, check, scheme) {
  console.log(`\n${scheme}: keyboard`);
  const [first] = h.available;
  const { page, context, frame } = await h.open({ scheme, answer: spawned() });
  const focused = () => frame.locator(":focus").evaluate((el) => el.getAttribute("aria-label") || el.labels?.[0]?.textContent.trim() || el.textContent.trim(), undefined, { timeout: 1500 }).catch(() => null);
  await page.keyboard.press("Tab");
  check((await focused()) === "Search the menu", `the first Tab lands on the search field (${await focused()})`);
  await page.keyboard.press("Tab");
  check((await focused()) === "All", `then the chips (${await focused()})`);
  for (let n = 0; n < 5; n += 1) await page.keyboard.press("Tab");
  check((await focused()) === `Add ${first.name}`, `then the first Add button (${await focused()})`);
  await page.keyboard.press("Space");
  check((await c.quantity(frame, first.name).innerText()) === "1" && (await focused()) === `One more ${first.name}`, "Space adds it and focus moves to the plus button");
  await page.keyboard.press("Enter");
  check((await c.quantity(frame, first.name).innerText()) === "2", "Enter on the plus button adds another");
  await page.keyboard.press("Shift+Tab");
  check((await focused()) === `One less ${first.name}`, "Shift+Tab reaches the minus button");
  const ring = await frame.locator(":focus").evaluate((el) => {
    const style = getComputedStyle(el);
    return style.outlineStyle !== "none" && parseFloat(style.outlineWidth) >= 2;
  });
  check(ring, "the focused control shows a focus ring");
  await page.keyboard.press("Enter");
  check((await c.quantity(frame, first.name).innerText()) === "1", "Enter on it removes one");
  const order = [];
  for (let n = 0; n < 60; n += 1) {
    await page.keyboard.press("Tab");
    order.push(await focused());
    if (order.at(-1) === "Review order") break;
  }
  check(order.includes("Deliver to") && order.includes("Clear"), "Tab passes the area and Clear on the way to Review order");
  check(order.at(-1) === "Review order", `Tab ends on Review order (${order.slice(-3)})`);
  await page.keyboard.press("Enter");
  await frame.getByText("Order ready to approve").waitFor({ timeout: 5000 });
  check((await h.calls(page)).length === 1, "Enter on Review order sends the order");
  await context.close();
}
