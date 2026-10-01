// SPDX-License-Identifier: AGPL-3.0-or-later
// What the round button and Enter do around a send, in a real browser: right after a message is accepted the
// button is already Stop (even while the chat's `turn.started` has not reached the page), so a second Enter or
// click neither sends over the running turn nor cancels it by accident; and a send the host refuses (429) or
// fails (500) leaves the text in the field, the button back to Send, and one plain line saying why.
//
// needs the stack (tools/up.sh). usage: node conformance/chat-send.mjs
import { browser, HOST, openHome, pause, sendFirst, settled, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Send");
const chromium = await browser();
const errors = [];
const field = (page) => page.locator("#text");
const button = (page) => page.locator('[data-slot="send"]');
const label = (page) => button(page).getAttribute("aria-label");
const problem = (page) => page.locator('[data-slot="error"]');

/** Holds back the chat's event frames from the first `turn.started` on, until `release()`. */
async function holdTurnStart(page) {
  const held = [];
  let armed = false;
  let holding = false;
  let toPage = null;
  await page.routeWebSocket(/\/ws\?/, (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((message) => server.send(message));
    server.onMessage((message) => {
      toPage = ws;
      if (armed && !holding && typeof message === "string" && message !== "pong") {
        try {
          holding = JSON.parse(message).type === "turn.started";
        } catch {}
      }
      if (holding) held.push(message);
      else ws.send(message);
    });
  });
  return {
    arm: () => (armed = true),
    held: () => held.length,
    release() {
      armed = false;
      holding = false;
      for (const message of held.splice(0)) toPage.send(message);
    },
  };
}

const context = await chromium.newContext({ viewport: { width: 420, height: 760 } });
const page = await context.newPage();
watchErrors(page, errors);
const sends = [];
const cancels = [];
page.on("request", (request) => {
  if (request.method() !== "POST") return;
  if (/\/send$/.test(request.url())) sends.push(request.postData());
  if (/\/cancel$/.test(request.url())) cancels.push(request.url());
});
const hold = await holdTurnStart(page);
await openHome(page);
await sendFirst(page, "echo: first");
await settled(page);
await page.locator("assistant-text").last().waitFor();

console.log("\na message is accepted while the turn has not started on the page");
hold.arm();
await field(page).fill("echo: second");
await button(page).click();
await page.waitForFunction(() => !document.querySelector("#text").value);
await pause(700);
check(hold.held() > 0, "the page has the message but not the start of its turn");
check((await label(page)) === "Stop", "the round button is Stop, as the turn is open");
await field(page).fill("echo: third");
await field(page).press("Enter");
await pause(300);
check(sends.length === 1 && cancels.length === 0, `Enter does not send over the running turn nor cancel it (${sends.length} sends after the first, ${cancels.length} cancels)`);
check((await field(page).inputValue()) === "echo: third", "the text stays in the field");
hold.release();
await settled(page);
await page.locator("chat-thread:not([data-working])").waitFor({ state: "attached" });
check(cancels.length === 0, "the second message's turn ran to its end");

console.log("\na refused or failed send");
for (const [status, body] of [[429, { error: "rate_limited", message: "Too many messages. Wait a minute." }], [500, "<h1>boom</h1>"]]) {
  await page.route(/\/send$/, (route) => route.fulfill({ status, contentType: typeof body === "string" ? "text/html" : "application/json", body: typeof body === "string" ? body : JSON.stringify(body) }), { times: 1 });
  await field(page).fill(`echo: refused ${status}`);
  await button(page).click();
  await problem(page).waitFor({ state: "visible", timeout: 5000 });
  const line = (await problem(page).innerText()).trim();
  check(line.length > 0 && !line.includes("\n"), `${status}: one plain line says why (${JSON.stringify(line)})`);
  check((await field(page).inputValue()) === `echo: refused ${status}`, `${status}: the text is kept`);
  await pause(500);
  check((await label(page)) === "Send" && !(await button(page).isDisabled()), `${status}: the button is Send again`);
}
await page.unroute(/\/send$/);

check(errors.filter((e) => !/Failed to load resource/.test(e)).length === 0, `no page errors ${errors.join("; ")}`);
await chromium.close();
finish();
