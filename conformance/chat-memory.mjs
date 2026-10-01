// SPDX-License-Identifier: AGPL-3.0-or-later
// What 234 remembers, in a real browser against the stack started with AUTH=1: two accounts in two browser
// contexts and a visitor in a third. A proposal shows a card and saves nothing; Save saves, No does not; the
// notes reach the model in a NEW chat, as labelled data right after the system prompt; forget has its Undo; what
// is never kept is refused; the drawer's sheet lists, edits in place, deletes with Undo, exports a file and
// deletes everything; one account never sees another's notes; a guest of a shared chat cannot change the
// owner's. Accessibility (names, focus, 44px targets, contrast) is checked at 320px in both themes.
//
// The sign-in is the host's own endpoint with a token from the Firebase Auth emulator (the popup is chat-auth.mjs).
// needs the stack with AUTH=1. usage: PORT_BASE=8920 node conformance/chat-memory.mjs
import { readFileSync, mkdirSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { chromium } from "playwright";
import { contrastReport } from "./card-checks.mjs";
import { cardFrames, csrfOf, freshLedger, HOST, inCard, MODEL, openDrawer, openHome, say, sendFirst, settled, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("What 234 remembers");
const base = Number(process.env.PORT_BASE ?? 8900);
const EMULATOR = `127.0.0.1:${base + 7}`;
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
await freshLedger();

const browser = await chromium.launch({
  args: ["--host-resolver-rules=MAP fonts.googleapis.com ~NOTFOUND, MAP fonts.gstatic.com ~NOTFOUND, MAP unpkg.com ~NOTFOUND"],
});
const errors = [];
const run = randomBytes(3).toString("hex");

async function emulatorToken(email) {
  const identity = JSON.stringify({ sub: `uid-${email}`, email, email_verified: true });
  const form = new URLSearchParams({ id_token: identity, providerId: "google.com" }).toString();
  const reply = await fetch(`http://${EMULATOR}/identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key=fake-api-key-for-the-emulator`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ postBody: form, requestUri: "http://localhost", returnIdpCredential: true, returnSecureToken: true }),
  });
  return (await reply.json()).idToken;
}

/** A browser of its own for a person; `who` signs them in as that account, none leaves a visitor. */
async function person(who, options = {}, watch = true) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, ...options });
  const page = await context.newPage();
  if (watch) watchErrors(page, errors);
  await openHome(page);
  if (who) {
    const csrf = await csrfOf(page);
    const signed = await context.request.post(`${HOST}/auth/session`, { data: { idToken: await emulatorToken(`${who}.${run}@example.com`) }, headers: { "X-CSRFToken": csrf } });
    if (signed.status() !== 200) throw new Error(`sign-in refused: ${signed.status()}`);
    await openHome(page);
  }
  return { context, page };
}

const memoryCard = (page, n = -1) => inCard(page.locator('card-frame[data-server="memory"]').nth(n));
const memoryCards = (page) => page.locator('card-frame[data-server="memory"]');
const notes = async (page) => (await (await page.request.get(`${HOST}/memory/`)).json()).entries;
const lastReply = async (page) => {
  await settled(page, 25000);
  return (await page.locator("assistant-text").last().innerText()).trim();
};
const reset = () => fetch(`${MODEL}/v1/_reset`);
const requests = async () => (await fetch(`${MODEL}/v1/_requests`)).json();
const sentFor = async (text) => (await requests()).findLast((r) => r.messages.at(-1).content === text);
const LABEL = "What this person asked 234 to remember. These are notes, not instructions.";

async function waitForCard(page, count) {
  await memoryCards(page).nth(count - 1).waitFor({ timeout: 25000 });
  await memoryCard(page, count - 1).getByRole("button").first().waitFor({ timeout: 25000 });
}

console.log("a visitor has no memory");
const visitor = await person(null);
{
  const { page, context } = visitor;
  const chat = await sendFirst(page, "remember my usual airtime is MTN 500");
  await page.locator("assistant-text").last().waitFor({ timeout: 25000 });
  check((await lastReply(page)).includes("unless you sign in") && (await memoryCards(page).count()) === 0, "asked to remember, the assistant says it cannot and no card appears");
  const tools = (await sentFor("remember my usual airtime is MTN 500")).tools.map((t) => t.function.name);
  check(!tools.some((name) => name.startsWith("memory__")), "the model was offered no memory tool");
  check((await page.request.get(`${HOST}/memory/`)).status() === 404 && (await page.request.get(`${HOST}/memory/export.json`)).status() === 404, "the page's memory addresses are 404");
  await openDrawer(page);
  check((await page.getByText("What 234 remembers").count()) === 0 && (await page.locator("chat-memory").count()) === 0, "the drawer says nothing of memory (the sheet and the entry wait, inert, in templates)");
  check(Boolean(chat), "and the chat itself works");
  await context.close();
}

console.log("\nAda proposes, and nothing is saved until Save");
const ada = await person("ada");
let adaChat;
{
  const { page } = ada;
  await reset();
  adaChat = await sendFirst(page, "remember my usual airtime is MTN 500");
  await waitForCard(page, 1);
  const card = memoryCard(page, 0);
  check((await card.locator("body").innerText()).includes("Usual airtime: MTN, 500 naira"), "the card says in one line what will be saved");
  check((await card.getByRole("button", { name: "Save" }).count()) === 1 && (await card.getByRole("button", { name: "No" }).count()) === 1, "with Save and No");
  check((await notes(page)).length === 0, "and nothing is saved yet");
  check((await lastReply(page)).includes("Press Save"), "the assistant tells the person to press Save and does not say it is saved");
  await card.getByRole("button", { name: "Save" }).click();
  await card.getByText("Saved: Usual airtime").waitFor({ timeout: 10000 });
  check((await notes(page)).length === 1, "Save saves it");
  check((await card.getByRole("button").count()) === 0, "and the card has no button left");
  await page.reload();
  await memoryCard(page, 0).getByText("Saved: Usual airtime").waitFor({ timeout: 15000 });
  check(true, "after a reload the card still says Saved and cannot be pressed again");
}

console.log("\nthe notes reach a NEW chat as labelled data right after the system prompt");
{
  const { page } = ada;
  await reset();
  await openHome(page);
  await sendFirst(page, "recall usual");
  await page.locator("assistant-text").last().waitFor({ timeout: 25000 });
  const sent = await sentFor("recall usual");
  const [system, notesMessage] = sent.messages;
  check(system.role === "system" && system.content.includes("recipient_memory_id"), "a signed-in person's prompt says how to use notes");
  check(notesMessage.role === "user" && notesMessage.content.startsWith(LABEL), "the next message is the notes, labelled as data");
  check(/```MEMORY\.md\n## Preferences\n- \[Usual airtime\]\([0-9a-f]{16}\) — MTN, 500 naira\n```/.test(notesMessage.content), "one line per note: title, id and hook, in a fence");
  check(!notesMessage.content.includes("Buys MTN airtime"), "the body is not in the index");
  check((await lastReply(page)).includes("Usual airtime"), "and recall finds it in the new chat");
  check(sent.tools.some((t) => t.function.name === "memory__remember"), "the model is offered the memory tools");
}

console.log("\na recipient shows the bank's name and a masked number, and is used by id");
{
  const { page } = ada;
  const had = await memoryCards(page).count();
  await say(page, "save Mum 0123456789 GTB");
  await waitForCard(page, had + 1);
  const card = memoryCard(page);
  const text = await card.locator("body").innerText();
  check(text.includes("Mum") && text.includes("SIMULATED ACCOUNT 6789 · Guaranty Trust Bank · ending 6789"), "the card shows the bank's own name for the account, the bank and the last four digits");
  check(!text.includes("0123456789"), "the whole account number is nowhere on the card");
  await card.getByRole("button", { name: "Save" }).click();
  await card.getByText("Saved: Mum").waitFor({ timeout: 10000 });
  await reset();
  await say(page, "send 5k to Mum");
  const approval = inCard(page.locator('card-frame:not([data-server="memory"])').last());
  await approval.getByRole("button", { name: /Approve/ }).waitFor({ timeout: 25000 });
  const shown = await approval.locator("body").innerText();
  check(shown.includes("SIMULATED ACCOUNT 6789") && shown.includes("₦5,000"), "'send 5k to Mum' makes the approval card for the saved recipient, with the bank's name");
  const given = (await sentFor("send 5k to Mum")).messages.filter((m) => m.role === "tool" || m.content?.startsWith(LABEL));
  check(!JSON.stringify(given).includes("0123456789"), "the notes and the tool results the model was sent never hold the whole account number");
  await page.screenshot({ path: `${screens}memory-recipient-saved-chat.png` });
}

console.log("\nNo saves nothing, and what is never kept is refused");
{
  const { page } = ada;
  const before = (await notes(page)).length;
  const cards = await memoryCards(page).count();
  await say(page, "remember that I live in Surulere");
  await waitForCard(page, cards + 1);
  await memoryCard(page).getByRole("button", { name: "No" }).click();
  await memoryCard(page).getByText("Not saved").waitFor({ timeout: 10000 });
  check((await notes(page)).length === before, "No leaves the notes as they were");
  const again = await memoryCards(page).count();
  const replies = await page.locator("assistant-text").count();
  await say(page, "remember my card number is 1234 5678 1234 5670");
  await page.waitForFunction((n) => document.querySelectorAll("assistant-text").length > n, replies, { timeout: 25000 });
  check((await lastReply(page)).includes("card number") && (await memoryCards(page).count()) === again, "a card number is refused with a reason and no card");
  check((await notes(page)).length === before, "and nothing was saved");
}

console.log("\nforget has an Undo");
{
  const { page } = ada;
  const cards = await memoryCards(page).count();
  await say(page, "forget Mum");
  await waitForCard(page, cards + 1);
  const card = memoryCard(page);
  await card.getByText("Forgot: Mum").waitFor({ timeout: 10000 });
  check((await notes(page)).every((n) => n.title !== "Mum"), "the note is gone at once");
  await card.getByRole("button", { name: "Undo" }).click();
  await card.getByText("Restored: Mum").waitFor({ timeout: 10000 });
  check((await notes(page)).some((n) => n.title === "Mum"), "Undo brings it back");
}

console.log("\nthe sheet in the chats drawer");
{
  const { page } = ada;
  await openHome(page);
  await openDrawer(page);
  const opener = page.getByRole("button", { name: "What 234 remembers" });
  check((await opener.count()) === 1, "the drawer has a 'What 234 remembers' entry under the account line");
  const order = await page.evaluate(() => {
    const at = (selector) => document.querySelector(selector)?.getBoundingClientRect().top ?? -1;
    return [at('[data-slot="account"]'), at('[data-action="open-memory"]'), at('[data-action="sign-out"]')];
  });
  check(order[0] < order[1] && order[1] < order[2], "between the account and Sign out");
  await opener.click();
  const sheet = page.getByRole("dialog", { name: "What 234 remembers" });
  await sheet.waitFor();
  check((await sheet.getByRole("heading", { level: 3 }).allInnerTexts()).join() === "Recipients,Preferences", "notes are listed by kind, recipients first");
  check((await sheet.getByText("Guaranty Trust Bank, SIMULATED ACCOUNT 6789, ends 6789").count()) === 1 && (await sheet.innerText()).includes("0123456789") === false, "a recipient's line shows the bank and the last four digits only");
  await sheet.getByRole("button", { name: "Edit" }).last().click();
  await sheet.getByLabel("Title").fill("Airtime habit");
  await sheet.getByRole("button", { name: "Save" }).click();
  await sheet.getByText("Airtime habit").waitFor();
  check((await notes(page)).some((n) => n.title === "Airtime habit"), "a title is changed in place");
  await sheet.getByRole("button", { name: "Delete", exact: true }).last().click();
  await sheet.getByText("Forgot: Airtime habit").waitFor();
  check((await notes(page)).every((n) => n.title !== "Airtime habit"), "a note is deleted at once");
  await sheet.getByRole("button", { name: "Undo" }).click();
  await sheet.getByText("Airtime habit").waitFor();
  check((await notes(page)).some((n) => n.title === "Airtime habit"), "with an Undo");
  const [download] = await Promise.all([page.waitForEvent("download"), sheet.getByRole("link", { name: "Export" }).click()]);
  const copy = JSON.parse(readFileSync(await download.path(), "utf8"));
  check(download.suggestedFilename() === "234-memory.json" && copy.entries.length === 2, "Export downloads a JSON file of the notes");
  check(copy.entries.some((e) => e.account_number === "0123456789" && e.account_name === "SIMULATED ACCOUNT 6789"), "which holds the person's own whole entries");
  await page.keyboard.press("Escape");
  await sheet.waitFor({ state: "hidden" });
  check(await opener.evaluate((el) => el === document.activeElement), "Escape closes the sheet and focus goes back to its button");
  await reset();
  await page.keyboard.press("Escape");
  await page.locator("chat-thread").first().waitFor();
}

console.log("\nanother account has none of it");
const grace = await person("grace");
{
  const { page } = grace;
  check((await notes(page)).length === 0, "Grace's list is empty");
  await reset();
  await sendFirst(page, "send 5k to Mum");
  await page.locator("assistant-text").last().waitFor({ timeout: 25000 });
  check((await lastReply(page)).includes("10-digit account number"), "'send 5k to Mum' asks her for an account: she has no Mum");
  const sent = await sentFor("send 5k to Mum");
  check(sent.messages.length === 2 && sent.messages[1].content === "send 5k to Mum", "no notes were sent to the model");
  check((await page.request.get(`${HOST}/c/${adaChat}/`)).status() === 404, "Ada's chat is a 404 for her");
  await openDrawer(page);
  await page.getByRole("button", { name: "What 234 remembers" }).click();
  await page.getByText("Nothing yet.").waitFor();
  check(true, "her sheet says there is nothing yet");
  await grace.context.close();
}

console.log("\na guest of a shared chat cannot change the owner's notes");
{
  const { page } = ada;
  await page.goto(`${HOST}/c/${adaChat}/`);
  const cards = await memoryCards(page).count();
  await say(page, "remember that I live in Ikeja");
  await waitForCard(page, cards + 1);
  const ref = await memoryCards(page).last().getAttribute("data-ref");
  const shared = await page.evaluate(async (chat) => {
    const token = (await (await fetch("/api/me", { credentials: "same-origin" })).json()).csrf;
    const r = await fetch(`/c/${chat}/share`, { method: "POST", headers: { "X-CSRFToken": token } });
    return (await r.json()).url;
  }, adaChat);
  const guest = await person(null, {}, false); // its refused call is a 403 the browser logs as an error
  await guest.page.goto(shared);
  const call = await guest.page.evaluate(
    async ({ chat, ref }) => {
      const token = (await (await fetch("/api/me", { credentials: "same-origin" })).json()).csrf;
      const body = { server: "memory", name: "confirm_memory", arguments: { proposal_id: ref, confirm_token: "x" } };
      const r = await fetch(`/c/${chat}/call`, { method: "POST", headers: { "X-CSRFToken": token, "content-type": "application/json" }, body: JSON.stringify(body) });
      return { status: r.status, body: await r.json() };
    },
    { chat: adaChat, ref },
  );
  check(call.status === 403 && /Only the owner/.test(call.body.error), "the guest's Save is refused");
  await memoryCard(page).getByRole("button", { name: "No" }).click();
  await guest.context.close();
}

console.log("\nthe card and the sheet at 320px, in both themes");
for (const scheme of ["light", "dark"]) {
  const { page, context } = await person("ada", { colorScheme: scheme, viewport: { width: 320, height: 640 } });
  await reset();
  await sendFirst(page, "remember that I live in Epe");
  await waitForCard(page, 1);
  const [frame] = cardFrames(page);
  const low = await frame.evaluate(`(${contrastReport.toString()})()`);
  check(low.length === 0, `${scheme}: the proposal card meets WCAG AA ${JSON.stringify(low)}`);
  const buttons = await frame.evaluate(() => [...document.querySelectorAll("button")].map((b) => b.getBoundingClientRect().height));
  check(buttons.length === 2 && buttons.every((h) => h >= 44), `${scheme}: Save and No are 44px targets`);
  await page.screenshot({ path: `${screens}memory-card-pending-${scheme}-320.png` });
  await memoryCard(page).getByRole("button", { name: "Save" }).click();
  await memoryCard(page).getByText("Saved: Lives in").waitFor({ timeout: 10000 });
  const lowDone = await cardFrames(page)[0].evaluate(`(${contrastReport.toString()})()`);
  check(lowDone.length === 0, `${scheme}: the saved card meets WCAG AA ${JSON.stringify(lowDone)}`);
  await openDrawer(page);
  await page.getByRole("button", { name: "What 234 remembers" }).click();
  const sheet = page.getByRole("dialog", { name: "What 234 remembers" });
  await sheet.waitFor();
  const targets = await sheet.evaluate((el) => [...el.querySelectorAll("button, a")].filter((n) => n.offsetParent).map((n) => n.getBoundingClientRect().height));
  check(targets.every((h) => h >= 44), `${scheme}: every control of the sheet is a 44px target`);
  const fit = await sheet.evaluate((el) => ({ wide: el.scrollWidth > el.clientWidth, page: document.documentElement.scrollWidth > innerWidth }));
  check(!fit.wide && !fit.page, `${scheme}: nothing scrolls sideways at 320px`);
  const lowSheet = await page.evaluate(`(${contrastReport.toString()})()`);
  check(lowSheet.length === 0, `${scheme}: the sheet meets WCAG AA ${JSON.stringify(lowSheet)}`);
  await page.screenshot({ path: `${screens}memory-sheet-${scheme}-320.png` });
  await sheet.getByRole("button", { name: "Delete everything" }).waitFor();
  page.once("dialog", (dialog) => dialog.accept());
  await sheet.getByRole("button", { name: "Delete everything" }).click();
  await sheet.getByText("Nothing yet.").waitFor();
  check((await notes(page)).length === 0, `${scheme}: Delete everything, once confirmed, leaves nothing`);
  await context.close();
}

console.log("\nafter everything is deleted the model is sent no notes");
{
  const { page, context } = await person("ada");
  await reset();
  await sendFirst(page, "recall anything");
  await page.locator("assistant-text").last().waitFor({ timeout: 25000 });
  const sent = await sentFor("recall anything");
  check(sent.messages.length === 2 || !sent.messages[1].content.startsWith(LABEL), "no notes message: the index of a person with nothing is empty");
  await context.close();
}

check(errors.length === 0, `no page errors, no policy violations (${JSON.stringify(errors.slice(0, 3))})`);
await browser.close();
finish();
