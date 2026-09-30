// SPDX-License-Identifier: AGPL-3.0-or-later
// Each visitor spends from an allowance of their own. Two browsers (two visitors) use the real host and the
// real connectors: both spend, and neither changes the other's limit; a refusal shows the visitor's own
// remainder in one line; neither can act on the other's card, chat or quote by replaying its ids, or by
// putting the other's visitor id in a header or in the body of a request; a checkout reference nobody holds
// finds nothing.
//
// needs the stack. usage: node conformance/chat-visitors.mjs
import { CHECKOUT, HOST, browser, freshLedger, inCard, say, seen, startChat, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("One daily allowance for each visitor");
await freshLedger();
const chromium = await browser();
const errors = [];
const FORTY_THOUSAND = 4_000_000;
const LEFT = "(₦20,000 left today)";

async function visitor(name) {
  const context = await chromium.newContext({ viewport: { width: 420, height: 900 } });
  const page = await context.newPage();
  watchErrors(page, errors);
  return { name, context, page, chat: null };
}

const cardFrame = ({ page }, i) => inCard(page.locator("card-frame").nth(i));
const refOf = ({ page }, i) => page.locator("card-frame").nth(i).getAttribute("data-ref");

async function askForACard(who, text) {
  const before = await who.page.locator("card-frame").count();
  if (who.chat) await say(who.page, text);
  else who.chat = await startChat(who.page, text);
  await who.page.waitForFunction((n) => document.querySelectorAll("card-frame").length > n, before, { timeout: 20000 });
  await cardFrame(who, before).getByRole("button", { name: /Approve/ }).waitFor({ timeout: 20000 });
  return before;
}

async function approveOnTheCard(who, i) {
  const popup = who.context.waitForEvent("page", { timeout: 15000 });
  await cardFrame(who, i).getByRole("button", { name: /Approve/ }).click();
  await (await popup).close();
}

const idOf = async ({ context }) => (await context.cookies()).find((c) => c.name === "visitor").value.split(":")[0];
const spent = async (owner) => (await (await fetch(`${CHECKOUT}/test/summary?owner=${owner}`)).json()).spentTodayKobo;
const threadText = ({ page }) => page.locator("chat-thread").evaluate((el) => el.textContent.replace(/\s+/g, " "));

/** The approval token of a card, read from the visitor's own event stream: only the browser that owns it is sent it. */
async function tokenOf({ page, chat }, ref) {
  return page.evaluate(async ({ chat, ref }) => {
    const controller = new AbortController();
    const reply = await fetch(`/c/${chat}/events?since=0`, { signal: controller.signal });
    const reader = reply.body.getReader();
    const decoder = new TextDecoder();
    let seenSoFar = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return null;
      seenSoFar += decoder.decode(value, { stream: true });
      for (const frame of seenSoFar.split("\n\n").slice(0, -1)) {
        const data = frame.split("\n").find((line) => line.startsWith("data: "));
        const event = data ? JSON.parse(data.slice(6)) : null;
        if (event?.type === "card" && event.ref === ref) {
          controller.abort();
          return event.payload.result._meta?.approvalToken ?? null;
        }
      }
    }
  }, { chat, ref });
}

/** A card's tool call sent to the host's relay by this visitor's page, with the visitor's own CSRF token. */
function relay({ page }, chat, body, headers = {}) {
  return page.evaluate(async ({ chat, body, headers }) => {
    const csrf = document.querySelector('meta[name="csrf-token"]').content;
    const reply = await fetch(`/c/${chat}/call`, {
      method: "POST",
      headers: { "content-type": "application/json", "X-CSRFToken": csrf, ...headers },
      body: JSON.stringify(body),
    });
    return { status: reply.status, text: await reply.text() };
  }, { chat, body, headers });
}

const approveCall = (ref, token) => ({ server: "paystack-pay", name: "approve_quote", arguments: { quote_id: ref, approval_token: token, displayed_amount_kobo: FORTY_THOUSAND } });

const alice = await visitor("Alice");
const bob = await visitor("Bob");

console.log("\nboth visitors spend");
for (const [i, what] of ["lunch", "dinner", "supper"].entries()) {
  const at = await askForACard(alice, `Pay ₦40,000 to Demo Kitchen for ${what}`);
  check(at === i, `Alice has a card for ${what}`);
}
await approveOnTheCard(alice, 0);
await approveOnTheCard(alice, 1);
const aliceId = await idOf(alice);
check((await spent(aliceId)) === 2 * FORTY_THOUSAND, "Alice has spent ₦80,000 of her day");

await askForACard(bob, "Pay ₦40,000 to Demo Kitchen for lunch");
await approveOnTheCard(bob, 0);
const bobId = await idOf(bob);
check((await spent(bobId)) === FORTY_THOUSAND && (await spent(aliceId)) === 2 * FORTY_THOUSAND, "Bob's ₦40,000 is approved on top of Alice's ₦80,000, and changes neither's total but his own");
check(!(await cardFrame(bob, 0).getByText(/left today/).count()), "Bob's card shows no refusal");

console.log("\na visitor's limit is their own");
await cardFrame(alice, 2).getByRole("button", { name: /Approve/ }).click();
check(await seen(cardFrame(alice, 2).getByText(LEFT).waitFor({ timeout: 10000 })), "Alice's third approval is refused on the card with her own remainder");
const line = (await cardFrame(alice, 2).getByText(LEFT).innerText()).replace(/\s+/g, " ");
check(line === "₦40,000 would take today's approved total above the daily limit of ₦100,000 (₦20,000 left today).", `in one line (${line})`);
check(!/visitor|everyone|other|shared/i.test(line), "with no word about anyone else");
check((await spent(aliceId)) === 2 * FORTY_THOUSAND, "and nothing was spent");
await say(alice.page, "Pay ₦40,000 to Demo Kitchen for breakfast");
check(await seen(alice.page.waitForFunction((needle) => document.querySelector("chat-thread").textContent.replace(/\s+/g, " ").includes(needle), `${LEFT}.`, { timeout: 20000 })), "a new quote from the chat is refused with the same line");

const at = await askForACard(bob, "Pay ₦40,000 to Demo Kitchen for dinner");
const bobsSecond = await refOf(bob, at);
const bobsToken = await tokenOf(bob, bobsSecond);
const sly = await relay(bob, bob.chat, { ...approveCall(bobsSecond, bobsToken), _meta: { owner: aliceId }, owner: aliceId }, { "X-Ledger-Owner": aliceId, "X-Owner": aliceId });
check(sly.status === 200 && JSON.parse(sly.text).structuredContent.quote.phase === "awaiting_checkout", "Bob's approval succeeds although his request names Alice in a header and in its body: they are ignored");
check((await spent(bobId)) === 2 * FORTY_THOUSAND && (await spent(aliceId)) === 2 * FORTY_THOUSAND, "and it was spent from Bob's day, not Alice's");
await say(bob.page, "Pay ₦40,000 to Demo Kitchen for supper");
check(await seen(bob.page.waitForFunction((needle) => document.querySelector("chat-thread").textContent.replace(/\s+/g, " ").includes(needle), `${LEFT}.`, { timeout: 20000 })), "Bob is refused at the same point with his own remainder, although Alice spent first");

console.log("\nneither can act on the other's card by replaying its ids");
const refs = { alice: await refOf(alice, 2), bob: bobsSecond };
const tokens = { alice: await tokenOf(alice, refs.alice), bob: bobsToken };
const waiting = "Status: waiting for the person to approve";
const timesSaid = (page, needle) => page.locator("chat-thread").evaluate((el, n) => el.textContent.split(n).length - 1, needle);
const known = await timesSaid(alice.page, waiting);
await say(alice.page, `status of ${refs.alice}`);
check(await seen(alice.page.waitForFunction(([n, was]) => document.querySelector("chat-thread").textContent.split(n).length - 1 > was, [waiting, known], { timeout: 20000 })), "Alice's own assistant does find her quote by its id (the control for the checks below)");
for (const [attacker, victim, key] of [[bob, alice, "alice"], [alice, bob, "bob"]]) {
  const before = { own: await spent(await idOf(attacker)), theirs: await spent(await idOf(victim)) };
  const replayed = await relay(attacker, attacker.chat, approveCall(refs[key], tokens[key]));
  check(replayed.status === 403 && /no card/i.test(replayed.text), `${attacker.name} cannot approve ${victim.name}'s card through their own chat: ${replayed.text.slice(0, 60)}`);
  const inTheirChat = await relay(attacker, victim.chat, approveCall(refs[key], tokens[key]));
  check(inTheirChat.status === 404, `nor through ${victim.name}'s chat (${inTheirChat.status})`);
  const withTheirId = await relay(attacker, attacker.chat, approveCall(refs[key], tokens[key]), { "X-Ledger-Owner": await idOf(victim) });
  check(withTheirId.status === 403, `nor with ${victim.name}'s id in a header (${withTheirId.status})`);
  check((await attacker.page.goto(`${HOST}/c/${victim.chat}/`)).status() === 404, `${attacker.name} cannot open ${victim.name}'s chat`);
  await attacker.page.goto(`${HOST}/c/${attacker.chat}/`);
  await say(attacker.page, `status of ${refs[key]}`);
  check(await seen(attacker.page.waitForFunction(() => document.querySelector("chat-thread").textContent.includes("QUOTE_NOT_FOUND"), null, { timeout: 20000 })), `${attacker.name}'s assistant is told there is no such quote when asked for ${victim.name}'s: the connector scopes by owner`);
  check((await spent(await idOf(attacker))) === before.own && (await spent(await idOf(victim))) === before.theirs, "no one's spending changed");
}
check(/awaiting_approval|Approve/.test(await cardFrame(alice, 2).locator("body").innerText()), "Alice's unapproved card is still waiting");

console.log("\na checkout reference nobody holds");
const guess = `qt-${[...crypto.getRandomValues(new Uint8Array(10))].map((b) => b.toString(16).padStart(2, "0")).join("")}-a1`;
const opened = await fetch(`${CHECKOUT}/sim/checkout/${guess}`);
const pressed = await fetch(`${CHECKOUT}/sim/checkout/${guess}/pay`, { method: "POST" });
check(opened.status === 404 && pressed.status === 404, `finds nothing and changes nothing (${opened.status}, ${pressed.status})`);

const unexpected = errors.filter((e) => !/ERR_FAILED|Failed to load resource|Applying inline style/.test(e));
check(unexpected.length === 0, `no page errors or policy violations ${unexpected.join("; ")}`);
await chromium.close();
finish();
