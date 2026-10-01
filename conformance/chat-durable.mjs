// SPDX-License-Identifier: AGPL-3.0-or-later
// The chat as a view of server state: a reload or a closed tab loses nothing, the turn finishes without a
// client, every tab of a visitor shows one conversation, chats run side by side without mixing, and the
// stream survives a dropped connection on either transport.
//
// needs the stack. usage: node conformance/chat-durable.mjs
import { browser, HOST, openHome, pause, say, seen, startChat, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Chat durability");
const chromium = await browser();
const words = (n) => [...Array(n).keys()].map((i) => `word${i}`).concat("END").join(" ");
const replyOf = async (page) => (await page.locator("[data-message]").allInnerTexts()).join(" ").replace(/\s+/g, " ").trim();
const reply = (page, n, timeout = 25000) => seen(page.waitForFunction(
  (text) => [...document.querySelectorAll("[data-message]")].map((n) => n.textContent).join(" ").replace(/\s+/g, " ").trim() === text,
  words(n), { timeout },
));

const context = await chromium.newContext({ viewport: { width: 420, height: 800 } });
await context.addInitScript(() => {
  window.__sockets = [];
  const Native = window.WebSocket;
  window.WebSocket = class extends Native { constructor(...args) { super(...args); window.__sockets.push(this); } };
});
const errors = [];

console.log("\na reload in the middle of a reply");
let page = await context.newPage();
watchErrors(page, errors);
const chatA = await startChat(page, "slow:60@0.1");
await page.locator("[data-message]").first().waitFor();
await pause(1200);
await page.reload();
const partial = await replyOf(page);
check(partial.startsWith("word0") && partial.length < words(60).length, `after the reload the reply so far is there (${partial.split(" ").length} words) and still streaming`);
check(await reply(page, 60), "and it finishes: every word once, in order, no repeat of what was already shown");

console.log("\nthe tab is closed, the turn goes on, and the chat is opened again");
await say(page, "slow:40@0.1");
await page.locator("[data-message]").nth(1).waitFor();
await page.close();
await pause(6500);
page = await context.newPage();
watchErrors(page, errors);
await page.goto(`${HOST}/c/${chatA}/`);
const later = await page.locator("[data-message]").allInnerTexts();
check(later.length === 2 && later[1].replace(/\s+/g, " ").trim() === words(40), "the reply that finished while no tab was open is complete");
check((await page.locator("chat-thread:not([data-working])").count()) === 1, "and the chat is not shown as working");

console.log("\ntwo tabs of one visitor");
const tabTwo = await context.newPage();
watchErrors(tabTwo, errors);
await tabTwo.goto(`${HOST}/c/${chatA}/`);
await say(page, "slow:30@0.1");
check(await seen(tabTwo.getByText("slow:30@0.1").waitFor({ timeout: 8000 })), "a message sent in one tab appears in the other");
const lastReply = async (tab) => (await tab.locator("[data-message]").last().innerText()).replace(/\s+/g, " ").trim();
const done30 = (tab) => seen(tab.waitForFunction((text) => [...document.querySelectorAll("[data-message]")].at(-1)?.textContent.replace(/\s+/g, " ").trim() === text, words(30), { timeout: 25000 }));
check((await done30(tabTwo)) && (await done30(page)) && (await lastReply(tabTwo)) === words(30), "and the reply streams into both");
check((await tabTwo.locator("[data-message]").count()) === (await page.locator("[data-message]").count()), "the tabs show the same number of replies");
await tabTwo.close();

console.log("\ntwo chats side by side");
const first = chatA;
const second = await startChat(page, "slow:50@0.1");
await page.locator("[data-message]").first().waitFor();
const other = await context.newPage();
watchErrors(other, errors);
await other.goto(`${HOST}/c/${first}/`);
await say(other, "slow:20@0.1");
check(await reply(page, 50), "the second chat finishes its own reply");
const mine = await other.locator("[data-message]").allInnerTexts();
check(mine.at(-1).replace(/\s+/g, " ").trim() === words(20), "while the first chat, running at the same time, has only its own");
check(!(await page.locator("chat-thread").innerText()).includes("word19 END"), "nothing from the first chat leaked into the second");
await openHome(page);
await page.getByRole("button", { name: "Chats" }).click();
check((await page.locator("chat-sheet li").count()) === 2, "both chats are in the list");
await page.locator('chat-sheet [data-slot="open"]').nth(1).click();
await page.waitForURL(/\/c\//);
check((await page.locator("[data-message]").count()) >= 1, "switching to a chat shows its conversation");
await other.close();
void second;

for (const transport of ["ws", "sse"]) {
  console.log(`\ntransport ${transport}`);
  const tab = await context.newPage();
  watchErrors(tab, errors);
  const urls = [];
  tab.on("request", (r) => urls.push(r.url()));
  const id = await startChat(tab, "slow:60@0.1", `?transport=${transport}`);
  await tab.locator("[data-message]").first().waitFor();
  await pause(800);
  if (transport === "ws") await tab.evaluate(() => window.__sockets.at(-1).close());
  else await tab.evaluate(() => document.querySelector("chat-thread").stream.restart());
  await pause(600);
  const via = await tab.evaluate(() => document.querySelector("chat-thread").stream.via);
  check(via === transport || via === null, `the page uses ${transport}`);
  check(transport === "ws" ? (await tab.evaluate(() => window.__sockets.length)) >= 2 : urls.some((u) => u.includes("/events")), transport === "ws" ? "a dropped socket is opened again at the cursor" : "the stream is opened again at the cursor");
  check(await reply(tab, 60), "and the reply is whole: no gap, no repeat");
  check(id.length === 32 && (await tab.locator("[data-message]").count()) === 1, "in one bubble");
  await tab.close();
}

await context.setOffline?.(false);
check(errors.length === 0, `no page errors or policy violations ${errors.join("; ")}`);
await chromium.close();
finish();
