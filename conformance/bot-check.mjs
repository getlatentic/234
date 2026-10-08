// SPDX-License-Identifier: AGPL-3.0-or-later
// The bot check before a first message (host/src/chat/bot_check.py, docs/bot-check.md), end to end with
// Cloudflare's published test keys: the real Turnstile script in a real browser and the real siteverify from the
// host. The home page makes no request to Cloudflare until a first message is sent; the first message carries a
// token and makes the chat; the next message carries none; a first message posted with no token, or with a
// token that is not one, is refused and makes no chat; and the page's policy allowed all of it.
//
// needs the stack with TURNSTILE=1 and the network (tools/up.sh). usage: node conformance/bot-check.mjs
import { browser, HOST, csrfOf, openHome, say, settled, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("The bot check before a first message");
const chromium = await browser();
const errors = [];
const cloudflare = (url) => new URL(url).hostname === "challenges.cloudflare.com";

const context = await chromium.newContext({ viewport: { width: 420, height: 800 } });
const page = await context.newPage();
watchErrors(page, errors);
const toCloudflare = [];
const posts = [];
page.on("request", (request) => {
  if (cloudflare(request.url())) toCloudflare.push(request.url());
  if (request.method() === "POST" && /\/c\/[0-9a-f]{32}\/(start|send)$/.test(request.url())) posts.push({ url: request.url(), body: request.postDataJSON() });
});

console.log("\nthe home page");
await openHome(page);
await page.waitForLoadState("networkidle");
check(toCloudflare.length === 0, `the home page makes no request to Cloudflare before a first message (${toCloudflare.length})`);
const me = await page.evaluate(async () => (await fetch("/api/me", { credentials: "same-origin" })).json());
check(typeof me.botCheck === "string" && me.botCheck.startsWith("1x"), `/api/me gives a visitor the site key (${me.botCheck})`);
check(!JSON.stringify(me).includes("1x0000000000000000000000000000000AA"), "and never the secret");
const policy = (await (await context.request.get(`${HOST}/`)).headers())["content-security-policy"];
check(/script-src [^;]*https:\/\/challenges\.cloudflare\.com/.test(policy) && /frame-src [^;]*https:\/\/challenges\.cloudflare\.com/.test(policy), "the page's policy lets it reach Turnstile's script and frame");

console.log("\nthe first message");
await page.fill("#text", "What does BVN mean?");
await page.getByRole("button", { name: "Send", exact: true }).click();
await page.waitForURL(/\/c\/[0-9a-f]{32}\//, { timeout: 40000 });
await settled(page, 30000);
check(toCloudflare.some((url) => url.includes("/turnstile/v0/api.js")), "Turnstile's script was fetched when the message was sent");
const first = posts.find((p) => p.url.endsWith("/start"));
check(typeof first?.body.botToken === "string" && first.body.botToken.length > 10, "the first message carried a token");
check((await page.locator("assistant-text").count()) >= 1, "the chat was made and the model answered");
check((await page.locator('[data-slot="bot-check"]').evaluate((el) => el.children.length)) === 0, "the widget was taken down again");

console.log("\nthe next message");
await say(page, "And what is NIN?");
await settled(page, 30000);
const second = posts.filter((p) => p.url.endsWith("/send")).at(-1);
check(second !== undefined && !("botToken" in second.body), "a message in a chat that exists carries no token");

console.log("\nforged first messages");
const csrf = await csrfOf(page);
const forge = (body) =>
  page.evaluate(
    async ({ body, csrf }) => {
      const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
      const response = await fetch(`/c/${id}/start`, { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json", "X-CSRFToken": csrf }, body: JSON.stringify(body) });
      return { status: response.status, answer: await response.json().catch(() => ({})), id };
    },
    { body, csrf },
  );
const bare = await forge({ text: "hello" });
check(bare.status === 403 && bare.answer.error === "bot_check", `a first message with no token is refused (${bare.status} ${bare.answer.error})`);
const mine = await page.evaluate(async () => (await (await fetch("/api/me")).json()).chats.length);
check(mine === 1, `and makes no chat (the visitor has ${mine})`);
const huge = await forge({ text: "hello", botToken: "x".repeat(3000) });
check(huge.status === 403, "a token that is far too long is refused without asking Cloudflare");

const unexpected = errors.filter((e) => !/Failed to load resource/.test(e));
check(unexpected.length === 0, `no page errors or policy violations ${unexpected.join("; ")}`);
await chromium.close();
finish();
