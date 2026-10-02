// SPDX-License-Identifier: AGPL-3.0-or-later
// The empty home and its starters, in a real browser: the wordmark and its one line above the composer, the
// starters below it (a whole message is sent once, a beginning is put in the field: see chat-starters.mjs for
// the beginnings; every one works end to end here), the chats
// button that exists only with earlier chats and never covers the transcript, no header or footer, the page in
// both themes on a phone, a 320px phone and a wide screen, and the contrast of everything the home paints.
//
// needs the stack (tools/up.sh). usage: node conformance/chat-home.mjs
import { mkdirSync } from "node:fs";
import { contrastReport } from "./card-checks.mjs";
import { browser, cardIn, freshLedger, HOST, openDrawer, openHome, seen, settled, suite, tokenColor, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Home");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
await freshLedger();
const chromium = await browser();
const errors = [];

const starters = (page) => page.locator("chat-starters button");
const starterTexts = (page) => starters(page).evaluateAll((buttons) => buttons.map((b) => b.dataset.text));
const starterLabels = (page) => starters(page).evaluateAll((buttons) => buttons.map((b) => b.textContent.trim()));
const sending = (page) => page.locator("chat-starters button:not([data-fill])");
const startPosts = (page) => {
  const posts = [];
  page.on("request", (request) => request.method() === "POST" && request.url().endsWith("/start") && posts.push(request.postDataJSON()));
  return posts;
};
const asked = (page, text) => seen(page.locator("assistant-text", { hasText: text }).first().waitFor({ timeout: 20000 }));
const cardText = (page) => cardIn(page).first().locator("body");
const visit = async (options = {}, watch = true) => {
  const context = await chromium.newContext({ viewport: { width: 420, height: 860 }, ...options });
  const page = await context.newPage();
  if (watch) watchErrors(page, errors);
  await openHome(page);
  return { context, page };
};

console.log("the home, light and dark");
for (const scheme of ["light", "dark"]) {
  const { context, page } = await visit({ colorScheme: scheme });
  const name = await page.locator('meta[name="application-name"]').getAttribute("content");
  const mark = page.locator('[data-slot="wordmark"]');
  const line = page.locator('[data-slot="tagline"]');
  check(name === "234" && (await mark.getAttribute("role")) === "img" && (await mark.getAttribute("aria-label")) === name, `${scheme}: the wordmark is the product name from the one setting, named for a screen reader`);
  const drawn = await mark.evaluate((el) => {
    const svg = el.querySelector("svg");
    const box = svg.getBoundingClientRect();
    return { text: el.innerText, texts: svg.querySelectorAll("text, tspan").length, paths: svg.querySelectorAll("path").length, height: box.height, width: box.width, ink: getComputedStyle(svg.querySelector("path.fill-mark")).fill, device: getComputedStyle(svg.querySelector("path.fill-accent")).fill, mint: getComputedStyle(svg.querySelector("path.fill-mark-mint")).fill };
  });
  check(drawn.text === "" && drawn.texts === 0 && drawn.paths >= 4, `${scheme}: it is drawn as paths, with no text and so no font (${drawn.paths} paths)`);
  check(drawn.ink === (await tokenColor(page, "mark")) && drawn.device === (await tokenColor(page, "accent")) && drawn.mint === (await tokenColor(page, "mark-mint")), `${scheme}: the numerals are the mark colour, the plus is the accent with a mint pill (${drawn.ink}, ${drawn.device}, ${drawn.mint})`);
  check(drawn.height >= 48 && drawn.width / drawn.height > 2.1 && drawn.width / drawn.height < 2.3, `${scheme}: it is ${Math.round(drawn.width)} by ${Math.round(drawn.height)}px, the proportions of the drawing`);
  const ratio = await page.evaluate(() => {
    const paint = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
    const rgba = (css) => { paint.clearRect(0, 0, 1, 1); paint.fillStyle = css; paint.fillRect(0, 0, 1, 1); return [...paint.getImageData(0, 0, 1, 1).data].slice(0, 3); };
    const lum = ([r, g, b]) => [r, g, b].map((v) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)).reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
    const a = lum(rgba(getComputedStyle(document.querySelector("path.fill-mark")).fill));
    const g = lum(rgba(getComputedStyle(document.body).backgroundColor));
    return (Math.max(a, g) + 0.05) / (Math.min(a, g) + 0.05);
  });
  check(ratio >= 4.5, `${scheme}: the numerals read against the page like text (${ratio.toFixed(2)}:1; the green pills are a graphic)`);
  await page.evaluate(() => document.fonts.ready);
  check((await page.evaluate(() => [...document.fonts].filter((face) => face.status === "loaded").length)) === 0, `${scheme}: the home loads no web font`);
  const fontRequests = [];
  page.on("request", (r) => /\.woff2?$/.test(r.url()) && fontRequests.push(new URL(r.url()).origin));
  await page.reload();
  await page.evaluate(() => document.fonts.ready);
  check(fontRequests.length === 0, `${scheme}: no font is requested on the home, from any origin`);
  const sentence = (await line.innerText()).trim();
  check(sentence.length > 20 && sentence.length <= 90 && sentence.split(/[.!?](?:\s|$)/).filter(Boolean).length === 1 && /approve/i.test(sentence), `${scheme}: one short sentence says what it does and that the person approves (${sentence.length} characters)`);
  const [m, l, f, s0] = await Promise.all([mark, line, page.locator('[data-slot="pill"]'), starters(page).first()].map((x) => x.boundingBox()));
  check(m.y + m.height < l.y + 1 && l.y + l.height < f.y && f.y + f.height < s0.y, `${scheme}: the wordmark, its line, the composer and the starters are in that order down the page`);
  check((await page.evaluate(() => document.activeElement?.id)) === "text" && (await page.locator("#text").getAttribute("placeholder")) === "Ask 234", `${scheme}: the composer keeps its placeholder "Ask 234" and has focus`);
  check((await page.locator("header, footer, nav, [role=banner], [role=contentinfo]").count()) === 0, `${scheme}: no header, footer or bar`);
  check((await page.locator('[data-action="chats"]').isVisible()) === false && (await page.locator('[data-action="chats"]').count()) <= 1, `${scheme}: no chats button when there are no chats`);
  const low = await page.evaluate(`(${contrastReport.toString()})()`);
  check(low.length === 0, `${scheme}: every text on the home meets WCAG AA contrast against what is behind it ${JSON.stringify(low)}`);
  const accentedText = await page.evaluate(async () => {
    const accent = (() => {
      const probe = document.createElement("i");
      probe.style.color = "var(--accent)";
      document.body.append(probe);
      const c = getComputedStyle(probe).color;
      probe.remove();
      return c;
    })();
    return [...document.querySelectorAll("body *")].filter((el) => el.getClientRects().length && el.textContent.trim() && el.children.length === 0 && getComputedStyle(el).color === accent).map((el) => el.textContent.trim());
  });
  check(accentedText.length === 0, `${scheme}: no text is drawn in the vivid accent (${JSON.stringify(accentedText)})`);
  const arrow = await page.locator('[data-slot="send"]').evaluate((el) => getComputedStyle(el).backgroundColor);
  check(arrow !== (await tokenColor(page, "primary")), `${scheme}: the empty composer's send is not the primary colour: nothing to send yet`);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${screens}home-${scheme}-1-empty.png` });
  await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => document.activeElement?.dataset.text);
  check(focused === (await starterTexts(page))[0], `${scheme}: Tab goes from the field to the first starter (the idle send button is skipped)`);
  const ring = await page.evaluate(() => {
    const style = getComputedStyle(document.activeElement);
    return { style: style.outlineStyle, width: style.outlineWidth, colour: style.outlineColor };
  });
  check(ring.style === "solid" && ring.width === "2px" && ring.colour === (await tokenColor(page, "primary")), `${scheme}: keyboard focus draws a 2px primary-colour ring (${ring.colour})`);
  await page.screenshot({ path: `${screens}home-${scheme}-2-starter-focused.png` });
  await context.close();
}

console.log("\na wide screen");
for (const scheme of ["light", "dark"]) {
  const { context, page } = await visit({ colorScheme: scheme, viewport: { width: 1200, height: 800 } });
  await page.evaluate(() => document.fonts.ready);
  const mark = await page.locator('[data-slot="wordmark"]').boundingBox();
  const pill = await page.locator('[data-slot="pill"]').boundingBox();
  check(Math.abs(mark.x + mark.width / 2 - 600) < 2 && Math.abs(pill.x + pill.width / 2 - 600) < 2 && pill.width <= 700, `${scheme}: the wordmark and the composer are centred and the composer is a column, not the screen (${Math.round(pill.width)}px)`);
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${screens}home-${scheme}-6-wide.png` });
  await context.close();
}

console.log("\nthe starters");
{
  const { context, page } = await visit();
  const texts = await starterLabels(page);
  check(texts.length >= 4 && texts.length <= 6, `there are ${texts.length} starters`);
  check(texts.every((t) => t.length <= 32) && new Set(texts).size === texts.length, `each is one line of at most 32 characters, none repeated (${Math.max(...texts.map((t) => t.length))} at most)`);
  check(await starters(page).evaluateAll((buttons) => buttons.every((b) => b.localName === "button" && b.type === "button" && b.querySelector("svg[aria-hidden=true]") && (b.hasAttribute("data-fill") ? b.dataset.text.endsWith(" ") && b.dataset.text !== b.textContent.trim() : b.dataset.text === b.textContent.trim()))), "each is a real button with a drawn icon, whose name is the message it sends or the beginning it offers");
  check((await page.getByRole("group", { name: "Suggestions" }).count()) === 1, "they are one named group");
  const wanted = ["airtime", "data", "transfer", "food", "pay"];
  check(wanted.every((kind) => texts.some((t) => new RegExp(kind === "pay" ? "^Pay " : kind === "transfer" ? "^Send " : kind === "food" ? "^Order " : kind, "i").test(t))), "they cover airtime, data, a transfer, food and paying a merchant");
  const targets = await starters(page).evaluateAll((buttons) => buttons.map((b) => Math.round(b.getBoundingClientRect().height)));
  check(Math.min(...targets) >= 44, `every target is at least 44px tall (${Math.min(...targets)})`);
  const columns = async (size) => {
    await page.setViewportSize(size);
    return starters(page).evaluateAll((buttons) => new Set(buttons.map((b) => Math.round(b.getBoundingClientRect().left))).size);
  };
  check((await columns({ width: 420, height: 860 })) === 2, "two columns on a phone");
  check((await columns({ width: 1200, height: 800 })) === 3, "three columns on a wide screen");
  await page.setViewportSize({ width: 320, height: 640 });
  const narrow = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, ok: [...document.querySelectorAll("chat-starters button")].every((b) => b.getBoundingClientRect().right <= innerWidth) }));
  check(narrow.scroll <= 320 && narrow.ok, "and at 320px nothing scrolls sideways or is cut off");
  await page.screenshot({ path: `${screens}home-light-3-phone-320.png` });
  await context.close();
}

console.log("\none press is one message");
{
  const { context, page } = await visit();
  const posts = startPosts(page);
  const first = await sending(page).last().evaluate((el) => el.dataset.text);
  await sending(page).last().evaluate((button) => {
    button.click();
    button.click();
  });
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  await settled(page);
  check(posts.length === 1 && posts[0].text === first, `a double press sent one request carrying exactly "${first}"`);
  check((await page.locator("[data-slot=thread] .self-end").count()) === 1 && (await page.locator("[data-slot=thread] .self-end").innerText()) === first, "and the transcript has that message once");
  const two = await visit();
  const twoPosts = startPosts(two.page);
  await two.page.evaluate(() => {
    const buttons = document.querySelectorAll("chat-starters button:not([data-fill])");
    buttons[0].click();
    buttons[1].click();
  });
  await two.page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  await settled(two.page);
  check(twoPosts.length === 1, "two different starters pressed in the same moment send one message");
  check(await starters(two.page).evaluateAll((buttons) => buttons.every((b) => b.disabled)), "every starter is off from the first press on");
  await two.context.close();
  check((await page.locator("chat-starters").isVisible()) === false, "the starters are gone once there is a chat");
  await page.reload();
  check((await page.locator("chat-starters").isVisible()) === false, "and stay gone when the chat is reloaded");
  const asFirst = await page.locator("#text").evaluate((el) => el.value);
  check(asFirst === "", "the composer is empty again after the starter was sent");
  await openHome(page);
  check(await page.locator("chat-starters").isVisible(), "a new empty home has them again");
  await context.close();
}

console.log("\na refused message leaves the starters usable");
{
  const { context, page } = await visit({}, false);
  await page.route("**/start", (route) => route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ error: "That did not go through." }) }));
  const wanted = await sending(page).first().evaluate((el) => el.dataset.text);
  await sending(page).first().click();
  await page.locator('[data-slot="error"]:not(.hidden)').waitFor();
  check((await page.locator("chat-thread[data-draft]").count()) === 1 && (await sending(page).first().isEnabled()), "the page is still the empty home and the starters can be pressed again");
  check((await page.locator("#text").inputValue()) === wanted, "and the message is in the field, to edit or send");
  await context.close();
}

console.log("\nthe chats button");
{
  const { context, page } = await visit({ viewport: { width: 320, height: 640 } });
  await page.locator("#text").fill("echo: an earlier chat");
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  await settled(page);
  const button = page.getByRole("button", { name: "Chats" });
  check(await button.isVisible(), "the button appears when the first chat exists");
  const spot = async () => button.evaluate((el) => ({ ...el.getBoundingClientRect().toJSON(), position: getComputedStyle(el).position, radius: parseFloat(getComputedStyle(el).borderTopLeftRadius) }));
  let b = await spot();
  check(b.position === "fixed" && b.left >= 8 && b.top >= 8 && b.left < 24 && b.top < 24 && b.width >= 44 && b.height >= 44 && b.radius >= 8 && (await button.locator("img").count()) === 1, `it is a 44px button with the 234 icon, fixed at the top left (${Math.round(b.left)}, ${Math.round(b.top)})`);
  check((await page.locator('[data-slot="pill"] [data-action="chats"]').count()) === 0, "and it is not inside the composer");
  const first = await page.locator("[data-slot=thread] > *").first().evaluate((el) => el.getBoundingClientRect().toJSON());
  check(first.top >= b.top + b.height, `the transcript starts below it (first line at ${Math.round(first.top)}, button ends at ${Math.round(b.top + b.height)})`);
  const styleTop = await page.evaluate(() => getComputedStyle(document.querySelector('[data-action="chats"]')).top);
  const source = await page.evaluate(() => [...document.styleSheets].flatMap((s) => [...s.cssRules]).map((r) => r.cssText).join("\n"));
  check(/safe-area-inset-top/.test(source) && /safe-area-inset-left/.test(source) && parseFloat(styleTop) >= 12, "it and the first line respect the safe-area insets (env() in the stylesheet; Chromium reports 0 for them)");
  await openHome(page);
  check(await button.isVisible(), "it is there on the empty home too, for the visitor with earlier chats");
  b = await spot();
  const markBox = await page.locator('[data-slot="wordmark"]').boundingBox();
  check(markBox.y >= b.top + b.height - 1 || markBox.x >= b.left + b.width, "and does not sit on the wordmark, even at 320px");
  await page.screenshot({ path: `${screens}home-light-4-with-chats.png` });
  await openDrawer(page);
  await page.screenshot({ path: `${screens}home-light-5-drawer-320.png` });
  check(await page.getByRole("button", { name: "Delete chat" }).first().isVisible(), "it opens the drawer with the chats and their delete buttons");
  check((await page.getByRole("link", { name: "New chat" }).isVisible()) === false, "New chat is hidden on the empty home (already there); Share too");
  await context.close();
}

console.log("\nevery starter works end to end");
// A starter that is a beginning ("Buy ₦500 MTN airtime for ") is finished by typing what only the person knows.
const run = async (starter, steps, finishing = "") => {
  const { context, page } = await visit();
  await page.getByRole("button", { name: starter, exact: true }).click();
  if (finishing) {
    check((await page.locator("chat-thread[data-draft]").count()) === 1, `${starter}: pressing it sends nothing`);
    await page.keyboard.type(finishing);
    await page.keyboard.press("Enter");
  }
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  await steps(page);
  await context.close();
};
await run("Buy ₦500 MTN airtime", async (page) => {
  check(await seen(cardText(page).getByText("MTN airtime").first().waitFor({ timeout: 20000 })) && (await page.locator("card-frame").count()) === 1, "airtime: the number the person typed makes the approval card");
  check((await page.locator("[data-slot=thread] .self-end").first().innerText()) === "Buy ₦500 MTN airtime for 08031234567", "airtime: the message is the beginning and the number, as one line");
}, "08031234567");
await run("Buy ₦1,000 MTN data", async (page) => {
  check(await seen(cardText(page).getByText("MTN data").first().waitFor({ timeout: 25000 })), "data: the plan is looked up and the approval card shows it");
}, "08031234567");
await run("Send ₦5,000 to a friend", async (page) => {
  check(await seen(cardText(page).getByText("₦5,000").first().waitFor({ timeout: 25000 })) && (await page.locator("card-frame").count()) === 1, "transfer: the approval card shows the amount");
}, "0000000000 Zenith");
await run("Order jollof rice for delivery", async (page) => {
  check(await seen(cardText(page).getByText("Jollof rice with fried chicken").first().waitFor({ timeout: 25000 })), "food: the menu card opens with the dish");
});
await run("Pay ₦2,500 to Ada Stores", async (page) => {
  check(await seen(cardText(page).getByText("Ada Stores").first().waitFor({ timeout: 25000 })) && (await cardText(page).innerText()).includes("₦2,500"), "pay: the approval card shows the merchant and the amount");
});
await run("What can you do?", async (page) => {
  check(await asked(page, "You approve every payment"), "help: it answers");
  await settled(page);
  const reply = await page.locator("assistant-text").last().innerText();
  const said = reply.toLowerCase();
  check(reply.length <= 200 && ["airtime", "data", "send money", "food", "merchant"].every((w) => said.includes(w)), `help: the answer is short and names what the connectors do (${reply.length} characters)`);
  check(!/loan|balance|savings|bill|crypto|invest/.test(said.replace("can't", "")), "and promises nothing the connectors do not do");
  await page.locator("#text").fill("What is my balance?");
  await page.keyboard.press("Enter");
  check(await asked(page, "I can't do that"), "and turns down what it cannot do, naming what it can");
});

check(errors.length === 0, `no page errors or policy violations ${errors.join("; ")}`);
await chromium.close();
finish();
