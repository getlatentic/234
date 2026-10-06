// SPDX-License-Identifier: AGPL-3.0-or-later
// The approval card as shared server state: an approval in one tab reaches the card in another, a payment
// recorded on the checkout page reaches an open card by the connector's signed webhook while every call the
// card could poll with is blocked (the connector, not this script, signs and sends it), a share link
// opens the chat on another device, and delete removes it.
//
// needs the stack. usage: node conformance/chat-cards.mjs
import { browser, cardIn, freshLedger, HOST, openHome, pause, say, seen, signedEvent, startChat, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Chat cards and sharing");
await freshLedger();
const chromium = await browser();
const errors = [];
const context = await chromium.newContext({ viewport: { width: 420, height: 800 } });

const one = await context.newPage();
watchErrors(one, errors);
const chat = await startChat(one, "Pay ₦2,500 to Demo Kitchen for lunch");
const cardOne = cardIn(one);
await cardOne.getByRole("button", { name: /Approve/ }).waitFor({ timeout: 20000 });
const two = await context.newPage();
watchErrors(two, errors);
await two.goto(`${HOST}/c/${chat}/`);
const cardTwo = cardIn(two);
check(await seen(cardTwo.getByRole("button", { name: /Approve/ }).waitFor({ timeout: 15000 })), "a second tab shows the pending approval, still actionable");

console.log("\nan approval in one tab reaches the other");
const popup = context.waitForEvent("page", { timeout: 15000 });
await cardOne.getByRole("button", { name: /Approve/ }).click();
const checkout = await popup;
check(await seen(cardTwo.getByRole("button", { name: /Approve/ }).waitFor({ state: "detached", timeout: 8000 })), "the card in the other tab leaves 'awaiting approval' without a reload");
check(await seen(cardTwo.getByText(/checkout/i).first().waitFor({ timeout: 8000 })), "and shows the checkout state the server holds");

console.log("\na payment on the checkout page reaches the open cards by the connector's MCP event");
const calls = [];
for (const page of [one, two]) {
  await page.route("**/call", (route) => { calls.push(route.request().url()); return route.abort(); });
}
await pause(2500);
const quote = await one.evaluate(() => document.querySelector("card-frame").dataset.ref);
check((await checkout.getByRole("link", { name: "Return to the chat" }).count()) === 0, "the checkout page offers no way back before the payment");
const started = Date.now();
await checkout.click("button:has-text('Pay with a test card')");
check(await seen(cardOne.getByText("Payment received").first().waitFor({ timeout: 8000 })), "the card shows the receipt");
const took = Date.now() - started;
// Paystack's (simulated) webhook, the connector's recheck and the quote.finished event each go through a local
// Queue that batches for up to a second, so the press is a few seconds from the card, not a poll away.
check(took < 6000, `within ${took} ms of the press, while every relay call from the page is blocked (${calls.length} refused), so nothing was polled: the connector's event told the host`);
check(new URL(checkout.url()).searchParams.get("back") === `/c/${chat}/`, "the checkout was opened with the chat it belongs to, for its way back");
check(checkout.isClosed() || (await seen(checkout.waitForEvent("close", { timeout: 4000 }))), "the checkout window closed itself after Paid");
check(await seen(cardTwo.getByText("Payment received").first().waitFor({ timeout: 8000 })), "the other tab's card shows it too");
check((await signedEvent("qt-not-a-quote")).status === 410, "an ending for a quote no chat holds ends that subscription (410)");
const forged = await fetch(`${HOST}/hooks/events`, { method: "POST", body: JSON.stringify({ name: "quote.finished", data: { quote_id: quote } }), headers: { "webhook-id": "evt_x", "webhook-timestamp": String(Math.floor(Date.now() / 1000)), "webhook-signature": "v1,AAAA", "content-type": "application/json" } });
check(forged.status === 401, "an unsigned or forged event is refused");

console.log("\nanother device");
await one.unroute("**/call");
check(await seen(one.getByText("Card: Payment received").first().waitFor({ timeout: 12000 })), "once the page can poll again the card settles and its note to the model is recorded");
await context.grantPermissions(["clipboard-read", "clipboard-write"]);
const shared = one.waitForResponse((r) => r.url().endsWith("/share"));
await one.getByRole("button", { name: "Chats" }).click();
await one.getByRole("button", { name: /open this chat on another device/i }).click();
const link = (await (await shared).json()).url;
check((await one.evaluate(() => navigator.clipboard.readText())) === link, "the link button copies a share link to the clipboard");
const other = await chromium.newContext({ viewport: { width: 420, height: 800 } });
const away = await other.newPage();
watchErrors(away, errors);
check((await away.goto(`${HOST}/c/${chat}/`)).status() === 404, "a browser without the visitor's cookie cannot open the chat");
check(link.startsWith(`${HOST}/join/`), "the link is a join address on this host");
await away.goto(link);
check(away.url() === `${HOST}/c/${chat}/`, "the link opens the chat on the other device");
check(await seen(away.getByText("Pay ₦2,500 to Demo Kitchen for lunch").first().waitFor({ timeout: 8000 })) && (await away.locator("card-frame").count()) === 1, "with its whole conversation, the card included");
await say(away, "thanks");
check(await seen(one.getByText("thanks", { exact: true }).waitFor({ timeout: 8000 })), "and what is said there appears in the first device's tab at once");
await openHome(away);
check((await away.locator("chat-sheet li").count()) === 1, "the chat is in that device's list");

console.log("\ndelete");
one.on("dialog", (dialog) => dialog.accept());
await openHome(one);
await one.getByRole("button", { name: "Chats" }).click();
await one.getByRole("button", { name: "Delete chat" }).click();
await one.waitForFunction(() => document.querySelectorAll("chat-sheet li").length === 0);
check((await one.locator("chat-sheet li").count()) === 0, "a deleted chat leaves the list");
check((await one.goto(`${HOST}/c/${chat}/`)).status() === 404, "and is gone");
check((await away.goto(`${HOST}/c/${chat}/`)).status() === 404, "for the other device too");

// The refused relay calls and the deliberate visits to missing chats are logged by the browser as errors.
const unexpected = errors.filter((e) => !/ERR_FAILED|Failed to load resource|Applying inline style/.test(e));
check(unexpected.length === 0, `no page errors or policy violations ${unexpected.join("; ")}`);
await other.close();
await chromium.close();
finish();
