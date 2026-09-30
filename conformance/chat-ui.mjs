// SPDX-License-Identifier: AGPL-3.0-or-later
// The chat page in a real browser, end to end: the list, the web components, streaming from the model,
// tool rows, the approval card behind the official AppBridge in a sandboxed frame, an approval through the
// relay to the checkout and back to a receipt, what the model was (and was not) sent, and the light and dark
// screenshots in docs/screens/.
//
// needs the stack (tools/up.sh). usage: node conformance/chat-ui.mjs
import { mkdirSync } from "node:fs";
import { HOST, MODEL, browser, cardIn, freshLedger, modelRequests, openDrawer, sendFirst, seen, settled, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Chat UI");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
await freshLedger();
const chromium = await browser();

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}`);
  const context = await chromium.newContext({ colorScheme: scheme, viewport: { width: 420, height: 800 } });
  const page = await context.newPage();
  const errors = watchErrors(page);

  const first = await page.goto(`${HOST}/`);
  check(first.ok(), "the home page renders");
  check(first.headers()["content-security-policy"]?.includes("script-src 'self'"), "the page carries a policy that allows only its own scripts");
  const cookie = (await context.cookies()).find((c) => c.name === "visitor");
  check(cookie?.httpOnly && cookie.sameSite === "Lax", "the visitor cookie is signed, HttpOnly and SameSite=Lax");

  check((await page.locator("chat-thread").getAttribute("data-last-seq")) === "0", "a new chat starts its stream at 0");

  await page.evaluate(() => {
    window.__arrivals = [];
    new MutationObserver((records) => {
      for (const r of records) for (const n of r.addedNodes.length ? r.addedNodes : [r.target]) window.__arrivals.push({ t: performance.now(), text: n.textContent });
    }).observe(document.querySelector('[data-slot="thread"]'), { childList: true, subtree: true, characterData: true });
  });
  check(Boolean(await sendFirst(page, "Pay ₦2,500 to Demo Kitchen for lunch")), "the first message makes the chat");
  check(await seen(page.locator("summary", { hasText: "Create payment quote" }).waitFor({ timeout: 15000 })), "a tool-call row appears for create_payment_quote, named as a person reads it");
  const frame = cardIn(page);
  check(await seen(frame.getByText("Demo Kitchen").first().waitFor({ timeout: 15000 })), "the approval card renders in its sandboxed frame through the official AppBridge");
  check((await page.locator("card-frame iframe").getAttribute("sandbox")) === "allow-scripts allow-same-origin", 'the frame in the page is the sandbox proxy, sandbox="allow-scripts allow-same-origin"');
  check((await page.frameLocator("card-frame iframe").locator("iframe").getAttribute("sandbox")) === "allow-scripts", 'and the card is in a frame of its own with sandbox="allow-scripts" and nothing else');
  check(await seen(page.getByText("I have prepared this for you").waitFor({ timeout: 20000 })), "the model's reply arrives after the tool result");
  const arrivals = await page.evaluate(() => window.__arrivals);
  check(arrivals.length >= 4 && arrivals.at(-1).t - arrivals[0].t > 400, `the reply streamed in pieces (${arrivals.length} updates over ${Math.round(arrivals.at(-1).t - arrivals[0].t)} ms)`);
  check(await seen(settled(page, 5000)), "the send button comes back when the turn has finished");
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${screens}chat-${scheme}-1-approve.png` });

  const popup = context.waitForEvent("page", { timeout: 15000 });
  await frame.getByRole("button", { name: /Approve/ }).click();
  const checkout = await popup.then((p) => p, () => null);
  check(Boolean(checkout) && checkout.url().includes("/sim/checkout/qt-"), "Approve went through the relay and opened the checkout in a new tab");
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${screens}chat-${scheme}-2-checkout.png` });
  await checkout?.click("button:has-text('Pay with a test card')");
  check(await seen(frame.getByText("Payment received").first().waitFor({ timeout: 15000 })), "the card followed the payment to a receipt");
  check(await seen(page.getByText("Card: Payment received").waitFor({ timeout: 8000 })), "the card's note reached the chat and shows as a short Card row");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${screens}chat-${scheme}-3-receipt.png` });

  await page.reload();
  const text = await page.locator("chat-thread").innerText();
  check(text.includes("Card: Payment received") && text.includes("I have prepared this for you"), "after a reload the stored history is the same conversation");
  check(await seen(cardIn(page).getByText("Payment received").first().waitFor({ timeout: 10000 })), "and the card comes back showing the receipt, not the first quote");

  await page.goto(`${HOST}/`);
  await openDrawer(page);
  check((await page.locator("chat-sheet li").count()) === 1 && (await page.locator("chat-sheet").innerText()).includes("Pay ₦2,500"), "the list shows the chat under its first message");
  await page.screenshot({ path: `${screens}list-${scheme}.png` });
  check(errors.length === 0, `no page errors or policy violations ${errors.join("; ")}`);
  await context.close();
}

const sent = (await modelRequests()).filter((r) => r.tools);
const wire = JSON.stringify(sent);
const tools = (sent[0].tools ?? []).map((t) => t.function.name).sort();
const appOnly = /__(approve_quote|verify_quote|decline_quote)$/;
check(tools.includes("paystack-pay__create_payment_quote") && tools.length > 2 && !tools.some((t) => appOnly.test(t)), `the model was offered the connectors' model-visible tools only, none of the card's own (${tools.join(", ")})`);
check(!wire.includes("approvalToken") && !wire.includes("/sim/checkout/") && !wire.includes("structuredContent"), "the model was never sent the approval token, the checkout link or structured content");
const last = sent.at(-1);
check(last.stream === true && last.tool_choice === "auto" && last.reasoning_effort === "low" && last.authorization === true, "each request carried stream, tool_choice auto, reasoning_effort low and a bearer key (value not recorded)");
check(!wire.includes("claude"), "no Claude model was used");
await chromium.close();
finish();
