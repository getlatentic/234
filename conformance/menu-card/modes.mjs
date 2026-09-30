// SPDX-License-Identifier: AGPL-3.0-or-later
// Full screen through the display-mode API, and pictures: an item's image_url loads only from an origin
// the view declares, and otherwise the drawing shows.
import { controls as c } from "./harness.mjs";

const MODES = { availableDisplayModes: ["inline", "fullscreen"] };
const PICTURE = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==", "base64");
const CDN = "https://cdn.merchant.test";
const CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:";

export async function fullScreen(h, check, scheme) {
  console.log(`\n${scheme}: full screen`);
  const [first] = h.available;
  const none = await h.open({ scheme });
  check((await none.frame.getByRole("button", { name: "Full screen", exact: true }).count()) === 0 || (await none.frame.getByRole("button", { name: "Full screen", exact: true }).isHidden()), "a host that lists no full screen gets no expand control");
  await none.context.close();
  const inlineOnly = await h.open({ scheme, hostContext: { availableDisplayModes: ["inline"] } });
  check(await inlineOnly.frame.getByRole("button", { name: "Full screen", exact: true }).isHidden(), "nor does a host that lists only inline");
  await inlineOnly.context.close();

  const { page, context, frame } = await h.open({ scheme, hostContext: MODES, viewport: { width: 480, height: 800 } });
  const expand = frame.getByRole("button", { name: "Full screen", exact: true });
  check(await expand.isVisible(), "the expand control shows when the host lists fullscreen");
  await c.add(frame, first.name).click();
  const before = await page.locator("#card").boundingBox();
  await expand.click();
  await frame.getByRole("button", { name: "Exit full screen", exact: true }).waitFor();
  check((await page.evaluate(() => window.__log.filter((e) => e.kind === "displaymode").map((e) => e.mode))).join() === "fullscreen", "pressing it sends ui/request-display-mode with fullscreen");
  await page.waitForTimeout(300);
  check((await frame.locator('[data-slot="collapse-glyph"]').isVisible()) && (await frame.locator('[data-slot="expand-glyph"]').isHidden()), "the control shows the collapse drawing while in full screen");
  const wide = await page.locator("#card").boundingBox();
  check(wide.width === 480 && wide.height === 800, `the host gives the frame the whole window (${wide.width}x${wide.height})`);
  check(await frame.locator("html").evaluate((el) => el.dataset.mode === "fullscreen"), "the card reads the mode the host set");
  const footer = await c.review(frame).boundingBox();
  check(footer.y + footer.height <= 800 && footer.y + footer.height > 700, "Review order sits at the bottom of the window");
  const list = await frame.locator('[data-slot="scroller"]').boundingBox();
  check(list.height > 400, `the list uses the room (${Math.round(list.height)} px tall)`);
  check((await c.quantity(frame, first.name).innerText()) === "1", "the cart is still there");
  await h.shot(page, "fullscreen", scheme);
  await page.keyboard.press("Escape");
  await frame.getByRole("button", { name: "Full screen", exact: true }).waitFor();
  await page.waitForTimeout(500);
  const after = await page.locator("#card").boundingBox();
  check(Math.abs(after.height - before.height) < 4 && after.width === 400 && (await frame.locator("html").evaluate((el) => el.dataset.mode === "inline")), `Escape returns to the inline card, the same size as before (${before.width}x${before.height}, then ${after.width}x${after.height})`);
  check((await page.evaluate(() => window.__log.filter((e) => e.kind === "displaymode").map((e) => e.mode))).join() === "fullscreen,inline", "by asking the host for inline");
  await expand.click();
  await frame.getByRole("button", { name: "Exit full screen", exact: true }).click();
  await frame.getByRole("button", { name: "Full screen", exact: true }).waitFor();
  check(await frame.locator("html").evaluate((el) => el.dataset.mode === "inline"), "the control leaves full screen too");
  await context.close();
}

export async function pictures(h, check, scheme) {
  console.log(`\n${scheme}: pictures and the policy`);
  const [first] = h.available;
  const withPicture = h.withMenu({ items: h.items.map((item) => (item.item_id === first.item_id ? { ...item, image_url: `${CDN}/jollof.png` } : item)) });
  const served = [];
  const routes = (page) => page.route(`${CDN}/**`, (route) => { served.push(route.request().url()); return route.fulfill({ contentType: "image/png", body: PICTURE }); });
  const tile = (frame) => c.rows(frame).first().locator('[data-slot="tile"]');

  const blocked = await h.open({ scheme, result: withPicture, routes });
  await blocked.page.waitForTimeout(300);
  check(served.length === 0, "an image from an origin the view did not declare is never requested");
  check((await tile(blocked.frame).locator("img").count()) === 0 && (await tile(blocked.frame).locator("use").count()) === 1, "the drawing shows in its place");
  check(blocked.errors.every((e) => /Content Security Policy|img-src/.test(e)), "the only complaint is the browser's policy violation");
  await blocked.context.close();

  const allowed = await h.open({ scheme, result: withPicture, routes, csp: CSP.replace("img-src data:", `img-src data: ${CDN}`) });
  await allowed.page.waitForTimeout(400);
  check((await tile(allowed.frame).locator("img").count()) === 1 && (await tile(allowed.frame).locator("img").evaluate((img) => img.complete && img.naturalWidth > 0)), "a declared origin's image loads into the tile");
  await h.shot(allowed.page, "picture", scheme);
  await allowed.context.close();

  const dead = await h.open({ scheme, result: withPicture, csp: CSP.replace("img-src data:", `img-src data: ${CDN}`), routes: (page) => page.route(`${CDN}/**`, (route) => route.abort()) });
  await dead.page.waitForTimeout(400);
  check((await tile(dead.frame).locator("img").count()) === 0 && (await tile(dead.frame).locator("use").count()) === 1, "an image that cannot load falls back to the drawing");
  await dead.context.close();

  const plain = h.withMenu({ items: h.items.map((item) => (item.item_id === first.item_id ? { ...item, image_url: "http://insecure.test/x.png" } : item)) });
  const insecure = await h.open({ scheme, result: plain, routes: (page) => page.route("http://insecure.test/**", (route) => { served.push("insecure"); return route.abort(); }) });
  check(!served.includes("insecure") && (await tile(insecure.frame).locator("use").count()) === 1, "an image that is not https is not requested at all");
  await insecure.context.close();

  const hostile = await h.open({ scheme });
  const escapes = await hostile.frame.locator("body").evaluate(async () => {
    const outcomes = {};
    try { await fetch("https://example.test/collect"); outcomes.fetch = "allowed"; } catch { outcomes.fetch = "blocked"; }
    const script = document.createElement("script");
    script.src = "https://example.test/x.js";
    outcomes.script = await new Promise((resolve) => { script.onload = () => resolve("allowed"); script.onerror = () => resolve("blocked"); document.head.append(script); });
    const image = new Image();
    outcomes.image = await new Promise((resolve) => { image.onload = () => resolve("allowed"); image.onerror = () => resolve("blocked"); image.src = "https://example.test/x.png"; });
    return outcomes;
  });
  check(Object.values(escapes).every((v) => v === "blocked"), `the sandbox policy blocks a fetch, a script and an image from an undeclared origin (${JSON.stringify(escapes)})`);
  await hostile.context.close();
}
