// SPDX-License-Identifier: AGPL-3.0-or-later
// A chat opens with the input ready: the home page is the composer (focused, nothing else on it), the first
// message makes the chat and the page carries on as that chat, "New chat" comes back to the same composer,
// and the list of chats is a drawer that is one tap away and never in the way.
//
// needs the stack (tools/up.sh). usage: node conformance/chat-start.mjs
import { mkdirSync } from "node:fs";
import { HOST, browser, openDrawer, pause, say, seen, sendFirst, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Chat start");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
const chromium = await browser();
const errors = [];

const focusedId = (page) => page.evaluate(() => document.activeElement?.id);
const rows = (page) => page.locator("chat-sheet li");
const rowTitles = (page) => page.locator('chat-sheet [data-slot="open"]').allInnerTexts();
const openChats = openDrawer;
const idle = (page, replies = 1) =>
  page.waitForFunction(
    (count) => document.querySelectorAll("[data-message]").length >= count && !document.querySelector("chat-thread").hasAttribute("data-working"),
    replies,
    { timeout: 25000 },
  );
const visibleText = (page) =>
  page.evaluate(() => {
    const seenText = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const box = node.parentElement.getBoundingClientRect();
      const style = getComputedStyle(node.parentElement);
      if (node.textContent.trim() && box.width > 1 && box.height > 1 && style.visibility !== "hidden" && node.parentElement.closest("template, dialog:not([open])") === null) seenText.push(node.textContent.trim());
    }
    return seenText;
  });

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}: a cold visit`);
  const context = await chromium.newContext({ colorScheme: scheme, viewport: { width: 420, height: 800 } });
  const page = await context.newPage();
  watchErrors(page, errors);
  const home = await page.goto(`${HOST}/`);
  check(home.ok() && new URL(page.url()).pathname === "/", "the home page opens at /");
  check((await focusedId(page)) === "text", "the input has focus with no click");
  check((await page.locator("chat-thread[data-draft]").count()) === 1, "the page is a chat that is not made yet");
  const shown = await visibleText(page);
  check(/approve/i.test(shown[0]) && shown.length === 1 + (await page.locator("chat-starters button").count()), `the only text on the page is the one line and the starters; the wordmark is a drawing (${JSON.stringify(shown)})`);
  check((await page.locator("header, footer, nav").count()) === 0, "no header, footer or bar");
  check((await page.locator('[data-action="chats"]').isVisible()) === false, "a visitor with no chats has no chats button");
  check((await page.title()) === "234" && (await page.locator("#text").getAttribute("placeholder")) === "Ask 234" && (await page.locator('[data-slot="wordmark"]').getAttribute("aria-label")) === "234" && shown.filter((t) => /234/.test(t)).length === 0, "the product name is the tab title, the composer's placeholder and the wordmark's name, and is written in no other visible text");
  const manifest = await (await context.request.get(`${HOST}/manifest.webmanifest`)).json();
  check(manifest.name === "234" && manifest.short_name === "234" && manifest.description === "Talk and do anything with 234." && (await page.locator('meta[name="application-name"]').getAttribute("content")) === "234", "the manifest and the application-name meta carry the name, and the manifest the tagline");
  const meta = (selector) => page.locator(selector).getAttribute("content");
  check((await meta('meta[name="description"]')) === manifest.description && (await meta('meta[property="og:title"]')) === "234" && (await meta('meta[property="og:description"]')) === manifest.description, "the meta description and the Open Graph tags carry the tagline");
  const iconResponses = await Promise.all([...manifest.icons.map((icon) => icon.src), "/static/chat/brand/favicon.svg", "/static/chat/brand/favicon.ico", "/static/chat/brand/apple-touch-icon.png"].map((path) => context.request.get(new URL(path, HOST).href)));
  check(iconResponses.every((r) => r.ok()) && manifest.icons.some((i) => i.purpose === "maskable"), `the manifest's icons (one maskable) and the favicon and touch icon are served (${iconResponses.length} files)`);
  check((await rows(page).count()) === 0, "a cold visit stores no chat (the list is empty)");
  await page.reload();
  check((await rows(page).count()) === 0, "and a second visit stores none either");
  await page.screenshot({ path: `${screens}start-${scheme}-1-composer.png` });

  console.log(`\n${scheme}: the first message`);
  await page.locator("chat-thread").evaluate((el) => (el.dataset.marker = "same page"));
  const historyBefore = await page.evaluate(() => history.length);
  const starts = [];
  page.on("request", (r) => r.url().endsWith("/start") && starts.push(r.url()));
  await page.locator("#text").click();
  const chatId = await sendFirst(page, "echo: **First** reply\\n\\n- one\\n- two");
  check(starts.length === 1, "one request made the chat");
  check(/^\/c\/[0-9a-f]{32}\/$/.test(new URL(page.url()).pathname), "the address became the chat's address");
  check((await page.locator("chat-thread").getAttribute("data-marker")) === "same page", "without loading another page");
  check((await page.evaluate(() => history.length)) === historyBefore, "and without adding a history entry");
  check(await seen(page.locator("assistant-text strong", { hasText: "First" }).waitFor({ timeout: 15000 })), "the reply streams into it, as Markdown");
  check((await rows(page).count()) === 1 && (await rowTitles(page))[0].startsWith("echo: **First**"), "the list gained the chat, named by the message, without a reload");
  await idle(page);
  await page.screenshot({ path: `${screens}start-${scheme}-2-first-reply.png` });
  await openChats(page);
  check((await page.locator('chat-sheet [aria-current="page"]').count()) === 1, "the chat on show is marked in the list");
  check(await page.getByRole("link", { name: "New chat" }).isVisible(), "New chat and Share are in the sheet now");
  await page.getByRole("button", { name: "Close" }).click();

  console.log(`\n${scheme}: the drawer, by keyboard`);
  await page.goto(`${HOST}/`);
  check(await page.getByRole("button", { name: "Chats" }).isVisible(), "a visitor with an earlier chat has the chats button, on the empty page too");
  await page.keyboard.press("Shift+Tab");
  check(await seen(page.getByRole("button", { name: "Chats" }).evaluate((b) => b === document.activeElement || Promise.reject())), "Shift+Tab reaches the Chats button");
  await page.keyboard.press("Enter");
  check(await seen(page.locator("chat-sheet dialog[open]").waitFor({ timeout: 2000 })), "Enter opens the list as a sheet");
  check(await page.evaluate(() => document.querySelector("chat-sheet dialog").contains(document.activeElement)), "and focus moves into it");
  check((await page.getByRole("link", { name: "New chat" }).isVisible()) === false, "a chat that is not made yet has no New chat or Share in it");
  await page.keyboard.press("Escape");
  check((await page.locator("chat-sheet dialog[open]").count()) === 0, "Escape closes it");
  check(await seen(page.getByRole("button", { name: "Chats" }).evaluate((b) => b === document.activeElement || Promise.reject())), "and focus returns to the button");
  await page.goto(`${HOST}/c/${chatId}/`);

  console.log(`\n${scheme}: a reload, and a reload in the middle of a reply`);
  await page.reload();
  check(await seen(page.locator("assistant-text strong", { hasText: "First" }).waitFor({ timeout: 8000 })), "a reload restores the chat");
  check((await focusedId(page)) !== "text", "and does not take the keyboard");
  await say(page, "slow:60@0.1");
  await page.locator("[data-message]").nth(1).waitFor();
  await pause(1500);
  await page.reload();
  const partial = await page.locator("[data-message]").last().innerText();
  check(partial.startsWith("word0") && partial.length < 60 * 8, `the reply so far is there after the reload (${partial.split(/\s+/).length} words)`);
  check(await seen(page.waitForFunction(() => document.querySelector("[data-message]:last-of-type")?.textContent.includes("END"), null, { timeout: 25000 })), "and the reply carries on to its end");
  await idle(page);
  const words = (await page.locator("[data-message]").last().innerText()).trim().split(/\s+/);
  check(words.length === 61 && words.every((w, i) => w === (i === 60 ? "END" : `word${i}`)), "every word once, in order");

  console.log(`\n${scheme}: New chat from inside a chat, and earlier chats`);
  await openChats(page);
  await page.getByRole("link", { name: "New chat" }).click();
  await page.waitForURL(`${HOST}/`);
  check((await focusedId(page)) === "text" && (await page.locator("chat-thread[data-draft]").count()) === 1, "New chat lands on the same ready composer");
  check((await rows(page).count()) === 1, "a visitor with an earlier chat still gets a fresh composer, with the list one tap away");
  const again = await visibleText(page);
  check(/approve/i.test(again[0]) && again.length === 1 + (await page.locator("chat-starters button").count()), "and it is as bare as the first time: its line and the starters");

  console.log(`\n${scheme}: two quick sends`);
  const before = await rows(page).count();
  await page.evaluate(() => {
    const form = document.querySelector('[data-slot="composer"]');
    form.elements.text.value = "echo: double";
    form.elements.text.dispatchEvent(new Event("input"));
    form.requestSubmit();
    form.requestSubmit();
  });
  await page.waitForURL(/\/c\/[0-9a-f]{32}\//);
  await idle(page);
  await pause(500);
  check((await rows(page).count()) === before + 1, "a double submit makes one chat");
  check((await page.locator(".self-end").count()) === 1, "and sends the message once");

  await page.goto(`${HOST}/`);
  const outcome = await page.evaluate(async () => {
    const thread = document.querySelector("chat-thread");
    const token = document.querySelector('meta[name="csrf-token"]').content;
    const send = (text) => fetch(thread.dataset.startUrl, { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json", "X-CSRFToken": token }, body: JSON.stringify({ text }) });
    const answers = await Promise.all([send("echo: first of two"), send("echo: second of two")]);
    return { statuses: answers.map((a) => a.status), url: thread.dataset.pageUrl };
  });
  check(outcome.statuses.every((s) => s === 200), `two requests to one new chat at the same moment are both accepted (${outcome.statuses})`);
  await page.goto(`${HOST}${outcome.url}`);
  await page.waitForFunction(() => document.querySelectorAll(".self-end").length === 2, null, { timeout: 8000 });
  await idle(page); // a round that starts after both messages arrived answers both in one reply
  check((await page.locator(".self-end").allInnerTexts()).sort().join() === "echo: first of two,echo: second of two", "they are two messages of one chat");
  await page.goto(`${HOST}/`);
  await openChats(page);
  check((await rows(page).count()) === before + 2, "and the list holds one chat for them, not two");

  console.log(`\n${scheme}: the list is newest first`);
  for (const text of ["echo: alpha", "echo: bravo", "echo: charlie"]) {
    await page.goto(`${HOST}/`);
    await sendFirst(page, text);
    await idle(page);
    await pause(300);
  }
  await page.goto(`${HOST}/`);
  await openChats(page);
  const titles = (await rowTitles(page)).slice(0, 3);
  check(titles.join() === "echo: charlie,echo: bravo,echo: alpha", `newest first: ${titles.join(" | ")}`);
  await page.screenshot({ path: `${screens}start-${scheme}-3-chats.png` });
  await context.close();
}

console.log("\na 320px phone");
const small = await chromium.newContext({ viewport: { width: 320, height: 568 }, colorScheme: "light" });
const phone = await small.newPage();
watchErrors(phone, errors);
await phone.goto(`${HOST}/`);
const layout = () =>
  phone.evaluate(() => {
    const floating = [...document.querySelectorAll("*")].filter((el) => ["fixed", "sticky"].includes(getComputedStyle(el).position) && el.getClientRects().length > 0).map((el) => el.localName);
    const form = document.querySelector('[data-slot="composer"]').getBoundingClientRect();
    return { floating, scrollWidth: document.documentElement.scrollWidth, width: innerWidth, formBottom: form.bottom, height: innerHeight, threadHeight: document.querySelector("chat-thread").getBoundingClientRect().height };
  });
let box = await layout();
check(box.scrollWidth <= box.width && box.formBottom < box.height - 20, "the empty page's composer sits above the bottom edge and nothing scrolls sideways");
check(box.floating.join() === "form", `the composer is the only thing fixed to the screen (${box.floating})`);
check(box.threadHeight >= box.height - 1, "the page fills the height (dvh)");
await sendFirst(phone, "echo: one two three");
await idle(phone);
await pause(400);
box = await layout();
check(box.scrollWidth <= box.width && box.formBottom <= box.height && box.formBottom > box.height - 20, "once there is a chat the composer sits on the bottom edge");
await openChats(phone);
const drawer = await phone.locator("chat-sheet dialog").boundingBox();
check(drawer.x === 0 && drawer.y === 0 && drawer.width <= 320 && drawer.height === 568, "the drawer fits the screen: its full height, at most its width");
await phone.screenshot({ path: `${screens}start-light-320-chats.png` });
await phone.getByRole("button", { name: "Close" }).click();
box = await layout();
check(box.scrollWidth <= box.width, "closing it leaves the page as it was");
await small.close();

check(errors.length === 0, `no page errors or policy violations ${errors.join("; ")}`);
await chromium.close();
finish();
