// SPDX-License-Identifier: AGPL-3.0-or-later
// The composer, in a real browser: a single rounded pill, centred while the page is empty and docked to the
// bottom once there is a chat; the round button that is a pale disabled arrow, a solid arrow, or a stop square;
// Enter, Shift+Enter and IME; a textarea that grows to about six lines; the placeholder that names the product
// (from the one setting); 320px, a keyboard's inset, reduced motion, light and dark; and that Stop really
// stops the turn on the server.
//
// needs the stack (tools/up.sh). usage: node conformance/chat-composer.mjs
import { mkdirSync } from "node:fs";
import { browser, HOST, openHome, pause, seen, settled, suite, tokenColor, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Composer");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
const chromium = await browser();
const errors = [];

const PLACEHOLDER = "Ask 234";
const LINE = 24;
const pill = (page) => page.locator('[data-slot="pill"]');
const field = (page) => page.locator("#text");
const send = (page) => page.locator('[data-slot="send"]');
const box = (page, selector) => page.locator(selector).evaluate((el) => el.getBoundingClientRect().toJSON());
const sendLook = (page) =>
  send(page).evaluate((el) => {
    const shown = (svg) => getComputedStyle(svg).display !== "none";
    const [arrow, stop] = el.querySelectorAll("svg");
    return { background: getComputedStyle(el).backgroundColor, disabled: el.disabled, label: el.getAttribute("aria-label"), arrow: shown(arrow), stop: shown(stop) };
  });
const words = (page) => page.locator("assistant-text").last().innerText().then((text) => text.trim().split(/\s+/).filter(Boolean).length);
const visibleText = (page) =>
  page.evaluate(() => {
    const found = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const box = node.parentElement.getBoundingClientRect();
      if (node.textContent.trim() && box.width > 1 && box.height > 1 && getComputedStyle(node.parentElement).visibility !== "hidden" && !node.parentElement.closest("template, dialog:not([open])")) found.push(node.textContent.trim());
    }
    return found;
  });
const visibleButtons = (page) => page.evaluate(() => [...document.querySelectorAll("button, a, input, textarea, select")].filter((el) => el.getClientRects().length > 0 && !el.closest("dialog:not([open]), template")).map((el) => el.getAttribute("aria-label") ?? el.localName));
const startRequests = (page) => {
  const seenRequests = [];
  page.on("request", (request) => request.method() === "POST" && /\/(start|send)$/.test(request.url()) && seenRequests.push(request.url()));
  return seenRequests;
};

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}: the empty page`);
  const context = await chromium.newContext({ colorScheme: scheme, viewport: { width: 420, height: 800 } });
  const page = await context.newPage();
  watchErrors(page, errors);
  await openHome(page);
  await pause(300);

  const height = 800;
  const pillBox = await pill(page).evaluate((el) => ({ ...el.getBoundingClientRect().toJSON(), radius: parseFloat(getComputedStyle(el).borderTopLeftRadius) }));
  const centre = pillBox.top + pillBox.height / 2;
  check(pillBox.radius >= pillBox.height / 2 - 1.5 && pillBox.height <= 64, `the composer is one rounded pill (${pillBox.height}px tall, corner ${pillBox.radius}px)`);
  check(centre < height / 2 && centre > height * 0.3, `it sits in the middle third of the viewport, with the wordmark above it and the starters below (centre at ${Math.round((centre / height) * 100)}%)`);
  const formTopBefore = await page.locator("form").evaluate((el) => el.getBoundingClientRect().top);
  check(Math.abs(pillBox.left + pillBox.width / 2 - 210) < 1, "and centred across");
  check(await page.evaluate(() => document.activeElement.id === "text"), "the field has focus with no click");
  check((await field(page).getAttribute("placeholder")) === PLACEHOLDER && (await page.getByRole("textbox", { name: PLACEHOLDER }).count()) === 1, `the placeholder and the accessible name are "${PLACEHOLDER}"`);
  const shown = await visibleText(page);
  check(shown.length === 1 + (await page.locator("chat-starters button").count()) && /approve/i.test(shown[0]), `the only text is one line and the starters (the wordmark is a drawing), no legal line (${shown.length} pieces)`);
  const controls = await visibleButtons(page);
  check(JSON.stringify(controls.slice(0, 2)) === JSON.stringify(["textarea", "Send"]) && controls.length === 2 + (await page.locator("chat-starters button").count()), `the only controls are the field, Send and the starters, and no chats button without chats (${controls.length})`);
  check((await page.locator("header, footer, nav, [role=banner], [role=contentinfo]").count()) === 0, "no header or footer");
  const round = await box(page, '[data-slot="send"]');
  check(Math.min(round.width, round.height) >= 44, `the round button is at least 44px (${round.width}x${round.height})`);
  check((await box(page, "#text")).right < round.left && (await page.locator('[data-slot="pill"] [data-action="chats"]').count()) === 0, "the field is on the left and send on the right, and the pill holds no chats button");

  console.log(`\n${scheme}: the round button`);
  const primary = await tokenColor(page, "primary");
  const sunken = await tokenColor(page, "sunken");
  let look = await sendLook(page);
  check(look.disabled && look.label === "Send" && look.background === sunken && look.arrow && !look.stop, `empty: a quiet disabled arrow on the neutral surface, not the primary colour (${look.background})`);
  await page.screenshot({ path: `${screens}composer-${scheme}-1-empty.png` });
  await page.keyboard.type("Pay 500 to Demo Kitchen");
  look = await sendLook(page);
  check(!look.disabled && look.background === primary && look.arrow, `with text: the primary-colour arrow, enabled (${look.background})`);
  await page.screenshot({ path: `${screens}composer-${scheme}-2-typing.png` });
  await field(page).fill("");
  check((await sendLook(page)).disabled, "emptied again: pale and disabled");
  await page.keyboard.type("   ");
  check((await sendLook(page)).disabled, "spaces alone do not enable it");
  await field(page).fill("");

  console.log(`\n${scheme}: Enter, Shift+Enter, IME`);
  const requests = startRequests(page);
  await page.keyboard.press("Enter");
  check(requests.length === 0, "Enter on an empty field sends nothing");
  await page.keyboard.type("first line");
  await page.keyboard.press("Shift+Enter");
  await page.keyboard.type("second line");
  check((await field(page).inputValue()) === "first line\nsecond line" && requests.length === 0, "Shift+Enter adds a line and sends nothing");
  check((await box(page, "#text")).height > 60, "and the field grows to show it");
  const composing = await page.evaluate(() => {
    const target = document.querySelector("#text");
    const press = (init) => {
      const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true, ...init });
      target.dispatchEvent(event);
      return event.defaultPrevented;
    };
    return { flagged: press({ isComposing: true }), legacy: press({ keyCode: 229 }) };
  });
  await pause(200);
  check(!composing.flagged && !composing.legacy && requests.length === 0, "Enter while an IME is composing (isComposing, or keyCode 229 as Safari sends it) does not send");
  const client = await context.newCDPSession(page);
  await client.send("Input.imeSetComposition", { text: "にほん", selectionStart: 3, selectionEnd: 3 });
  await page.keyboard.press("Enter");
  await pause(200);
  check(requests.length === 0, "and a real composition, started through the browser's own IME path, is not sent by Enter");
  await client.send("Input.insertText", { text: "" });
  await field(page).fill("");
  check((await box(page, "#text")).height <= 45, "clearing the field brings it back to one line");

  console.log(`\n${scheme}: growth to about six lines, then a scroll`);
  for (let line = 1; line <= 12; line += 1) {
    await page.keyboard.type(`line ${line}`);
    if (line < 12) await page.keyboard.press("Shift+Enter");
  }
  const grown = await field(page).evaluate((el) => ({ height: el.getBoundingClientRect().height, scrolls: el.scrollHeight > el.clientHeight + 1, overflow: getComputedStyle(el).overflowY }));
  check(grown.height >= 6 * LINE && grown.height <= 6 * LINE + 24, `twelve lines show about six (${grown.height}px = ${Math.round((grown.height - 20) / LINE)} lines and the padding)`);
  check(grown.scrolls && grown.overflow === "auto", "the rest scrolls inside the field");
  check((await box(page, '[data-slot="send"]')).bottom <= (await pill(page).evaluate((el) => el.getBoundingClientRect().bottom)) && (await box(page, '[data-slot="send"]')).top > (await box(page, "#text")).top, "the buttons stay at the bottom edge of a tall pill");
  await field(page).fill("");

  console.log(`\n${scheme}: the first message docks the pill`);
  await page.evaluate(() => {
    window.__dock = null;
    const thread = document.querySelector("chat-thread");
    new MutationObserver(() => {
      const form = document.querySelector("form");
      window.__dock ??= { animations: form.getAnimations().length, top: form.getBoundingClientRect().top, at: performance.now() };
    }).observe(thread, { attributes: true, attributeFilter: ["data-draft"] });
  });
  await page.keyboard.type("echo: docked");
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  await pause(150);
  const dock = await page.evaluate(() => window.__dock);
  check(dock && dock.animations === 1, "docking plays one short animation");
  check(dock && Math.abs(dock.top - formTopBefore) < 3, `it starts from where the pill was (${Math.round(dock?.top)}px, was ${Math.round(formTopBefore)}px)`);
  await pause(500);
  const docked = await pill(page).evaluate((el) => el.getBoundingClientRect().toJSON());
  check(docked.bottom > 800 - 16 && docked.bottom <= 800 - 8, `it ends docked at the bottom edge (pill bottom ${docked.bottom} of 800)`);
  check((await page.evaluate(() => document.querySelector("form").getAnimations().length)) === 0, "with no animation left running");
  check(await seen(page.locator("assistant-text", { hasText: "docked" }).waitFor({ timeout: 15000 })), "the transcript has the reply");
  await settled(page);
  check((await field(page).inputValue()) === "" && (await sendLook(page)).disabled, "the field is empty again and the button is the quiet arrow");
  check(await page.evaluate(() => document.activeElement.id === "text"), "and the field keeps the keyboard");
  await page.screenshot({ path: `${screens}composer-${scheme}-4-docked.png` });

  console.log(`\n${scheme}: a reload opens docked`);
  await page.reload();
  const early = await pill(page).evaluate((el) => el.getBoundingClientRect().bottom);
  check(early > 800 - 16 && (await page.evaluate(() => document.querySelector("form").getAnimations().length)) === 0, "a reload of a chat shows the docked pill with no animation");
  check(await page.evaluate(() => document.activeElement.id !== "text"), "and does not take the keyboard");

  console.log(`\n${scheme}: Stop`);
  await field(page).click();
  await page.keyboard.type("slow:60@0.1");
  const cancels = [];
  page.on("request", (request) => request.url().endsWith("/cancel") && cancels.push(request.url()));
  await send(page).click();
  await page.waitForFunction(() => document.querySelector('[data-slot="send"]').getAttribute("aria-label") === "Stop");
  await send(page).click({ force: true });
  await pause(1200);
  check(cancels.length === 0 && (await page.locator("chat-thread[data-working]").count()) === 1 && (await words(page)) > 3, "a second press on the button in the moment it turns into Stop stops nothing");
  await page.locator("assistant-text").nth(1).waitFor({ timeout: 15000 });
  look = await sendLook(page);
  check(!look.disabled && look.label === "Stop" && look.stop && !look.arrow && [await tokenColor(page, "ink"), await tokenColor(page, "ink-2")].includes(look.background), `while the reply streams the button is a solid Stop square, in ink and not the primary colour (${look.label})`);
  await pause(900);
  await page.screenshot({ path: `${screens}composer-${scheme}-3-streaming.png` });
  const before = startRequests(page).length;
  await field(page).fill("typed while it streams");
  await page.keyboard.press("Enter");
  await pause(200);
  check(startRequests(page).length === before && (await sendLook(page)).label === "Stop", "Enter while a reply streams does not send");
  await field(page).fill("");
  await pause(700);
  const stoppedAt = await words(page);
  await page.getByRole("button", { name: "Stop" }).click();
  await settled(page, 6000);
  look = await sendLook(page);
  check(look.label === "Send" && look.disabled && look.arrow, "Stop returns the button to a quiet Send");
  const kept = await words(page);
  await pause(1800);
  check((await words(page)) === kept && kept >= stoppedAt && kept < 60, `the reply stopped growing at ${kept} of 61 words`);
  check(!(await page.locator("assistant-text").last().innerText()).includes("END"), "and never reached its end");
  await page.reload();
  check((await words(page)) === kept && (await page.locator("chat-thread[data-working]").count()) === 0, "a reload shows the same reply, and the chat is not working");
  await page.locator("#text").fill("echo: after the stop");
  await page.keyboard.press("Enter");
  check(await seen(page.locator("assistant-text", { hasText: "after the stop" }).waitFor({ timeout: 15000 })), "the chat carries on: the next message is answered");
  await settled(page);
  const counted = await page.locator("chat-thread").evaluate(async (el) => {
    const answer = await fetch(el.dataset.eventsUrl.replace(/events$/, "cancel"), { method: "POST", headers: { "content-type": "application/json", "X-CSRFToken": (await (await fetch("/api/me", { credentials: "same-origin" })).json()).csrf }, body: "{}" });
    return answer.json();
  });
  check(counted.cancelled === false, "stopping a chat that is idle changes nothing");
  await context.close();
}

console.log("\na quiet stop: reduced motion");
{
  const context = await chromium.newContext({ viewport: { width: 420, height: 800 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  watchErrors(page, errors);
  await openHome(page);
  await page.evaluate(() => {
    window.__animated = 0;
    new MutationObserver(() => (window.__animated += document.querySelector("form").getAnimations().length)).observe(document.querySelector("chat-thread"), { attributes: true });
  });
  await page.keyboard.type("echo: calm");
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  await pause(60);
  const bottom = await pill(page).evaluate((el) => el.getBoundingClientRect().bottom);
  check((await page.evaluate(() => window.__animated)) === 0 && bottom > 800 - 16, "with prefers-reduced-motion the pill is docked at once and nothing is animated");
  await context.close();
}

console.log("\na 320px phone");
{
  const context = await chromium.newContext({ viewport: { width: 320, height: 568 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  watchErrors(page, errors);
  await openHome(page);
  await pause(300);
  const fits = () =>
    page.evaluate(() => {
      const pill = document.querySelector('[data-slot="pill"]').getBoundingClientRect();
      const inside = [...document.querySelectorAll('[data-slot="pill"] button, #text')].every((el) => {
        const r = el.getBoundingClientRect();
        return r.left >= pill.left - 0.5 && r.right <= pill.right + 0.5 && r.top >= pill.top - 0.5 && r.bottom <= pill.bottom + 0.5;
      });
      return { scroll: document.documentElement.scrollWidth, left: pill.left, right: pill.right, top: pill.top, bottom: pill.bottom, inside, height: innerHeight };
    });
  let now = await fits();
  check(now.scroll <= 320 && now.left >= 16 - 0.5 && now.right <= 320 - 16 + 0.5 && now.inside, `the pill fits between the gutters and holds its controls (${Math.round(now.left)}..${Math.round(now.right)})`);
  check(await page.evaluate(() => document.querySelector("meta[name=viewport]").content.includes("viewport-fit=cover") && document.querySelector("meta[name=viewport]").content.includes("interactive-widget=resizes-content")), "the viewport asks for the full screen and for the layout to shrink with the keyboard");

  for (const name of ["Northwind Agent Checkout Demos", "Supercalifragilisticexpialidos"]) {
    const long = `Ask ${name}`;
    await field(page).evaluate((el, text) => {
      el.placeholder = text;
      el.dispatchEvent(new Event("input"));
    }, long);
    now = await fits();
    const clipped = await field(page).evaluate((el) => el.scrollHeight > el.clientHeight + 1);
    check(name.length === 30 && now.scroll <= 320 && now.inside && now.right <= 320 - 16 + 0.5, `a product name of ${name.length} characters (${name.includes(" ") ? "words" : "one long word"}) keeps the pill inside the screen`);
    check(!clipped, `and the placeholder is shown whole, not clipped (the field is ${Math.round((await box(page, "#text")).height)}px tall)`);
    await page.screenshot({ path: `${screens}composer-light-6-phone-long-name${name.includes(" ") ? "" : "-one-word"}.png` });
  }
  await field(page).evaluate((el) => {
    el.placeholder = "Ask 234";
    el.dispatchEvent(new Event("input"));
  });

  const keyboardTop = async (inset) => {
    await page.evaluate((px) => document.documentElement.style.setProperty("--keyboard-inset", `${px}px`), inset);
    await pause(50);
    return fits();
  };
  now = await keyboardTop(260);
  check(now.bottom <= 568 - 260 && now.top > 0, `a keyboard of 260px on the empty page: the pill stays above it (bottom at ${Math.round(now.bottom)} of ${568 - 260})`);
  await keyboardTop(0);
  await page.screenshot({ path: `${screens}composer-light-5-phone.png` });

  await field(page).fill("echo: phone");
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  await settled(page);
  await pause(400);
  now = await fits();
  check(now.bottom <= 568 && now.bottom > 568 - 20 && now.scroll <= 320, "docked on the phone: the pill sits on the bottom edge and nothing scrolls sideways");
  now = await keyboardTop(260);
  check(now.bottom <= 568 - 260 + 1 && now.bottom > 568 - 260 - 20, `docked, a keyboard of 260px lifts the pill to sit on it (bottom at ${Math.round(now.bottom)})`);
  await keyboardTop(0);

  await page.setViewportSize({ width: 320, height: 300 });
  await pause(200);
  now = await fits();
  check(now.bottom <= 300 && now.bottom > 300 - 20, "when the browser shrinks the layout for the keyboard (300px left), the docked pill follows the new bottom");
  await openHome(page);
  await page.setViewportSize({ width: 320, height: 300 });
  await pause(300);
  now = await fits();
  check(now.top > 0 && now.bottom <= 300, `and the empty page's pill stays whole on screen (${Math.round(now.top)}..${Math.round(now.bottom)} of 300)`);
  await context.close();
}

console.log("\nthe keyboard's inset");
{
  const context = await chromium.newContext({ viewport: { width: 320, height: 568 } });
  const page = await context.newPage();
  await openHome(page);
  const cases = await page.evaluate(async () => {
    const { keyboardInset } = await import("/static/chat/keyboard.js");
    return [
      keyboardInset({ scale: 1, height: 568, offsetTop: 0 }, 568),
      keyboardInset({ scale: 1, height: 300, offsetTop: 0 }, 568),
      keyboardInset({ scale: 1, height: 300, offsetTop: 40 }, 568),
      keyboardInset({ scale: 2, height: 284, offsetTop: 0 }, 568),
      keyboardInset({ scale: 1, height: 600, offsetTop: 0 }, 568),
    ];
  });
  check(JSON.stringify(cases) === JSON.stringify([0, 268, 228, 0, 0]), `the inset is what the visual viewport lost at the bottom, and nothing when pinch-zoomed (${cases})`);
  const published = await page.evaluate(() => document.documentElement.style.getPropertyValue("--keyboard-inset"));
  check(published === "0px", "and it is published on the page (0px with no keyboard)");
  await context.close();
}

check(errors.length === 0, `no page errors or policy violations ${errors.join("; ")}`);
await chromium.close();
finish();
