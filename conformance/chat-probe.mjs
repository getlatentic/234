// SPDX-License-Identifier: AGPL-3.0-or-later
// The host's half of the card protocol, tested with a card written on the official App class (the probe
// card): the tools/call relay and its visibility rules, ui/message, ui/update-model-context, ui/open-link,
// and what the model is sent afterwards.
//
// needs a stack whose connector serves the probe card: `PORT_BASE=8940 tools/up.sh probe`
// usage: PORT_BASE=8940 node conformance/chat-probe.mjs
import { browser, modelRequests, seen, startChat, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Host card protocol, with the probe card");
const chromium = await browser();
const context = await chromium.newContext();
const page = await context.newPage();
const errors = watchErrors(page);

await startChat(page, "Pay ₦2,500 to Demo Kitchen for lunch");
await page.getByText("I have prepared this for you").waitFor({ timeout: 20000 });
const frame = () => page.frames().find((f) => new URL(f.url()).pathname === "/view");
const probe = (fn, ...args) => frame().evaluate(([f, a]) => window.probe[f](...a), [fn, args]);
const last = async () => (await frame().evaluate(() => window.__probe.results)).at(-1);
await frame().evaluate(() => new Promise((ok) => { const t = setInterval(() => window.__probe?.token && (clearInterval(t), ok()), 50); }));
const { quote, token } = await frame().evaluate(() => ({ quote: window.__probe.quote, token: window.__probe.token }));
check(quote?.phase === "awaiting_approval" && typeof token === "string", "the card received the quote and the approval token in _meta");

await probe("callTool", "approve_quote", { quote_id: quote.id, approval_token: token, displayed_amount_kobo: quote.amount.kobo });
let r = await last();
check(r.ok && r.value.structuredContent.quote.phase === "awaiting_checkout", "an app-only approve_quote is relayed to the connector and its result comes back as the JSON-RPC response");
await probe("callTool", "approve_quote", { quote_id: quote.id, approval_token: "wrong", displayed_amount_kobo: quote.amount.kobo });
r = await last();
check(r.ok && r.value.isError === true, "a wrong token is refused by the connector (tool error)");
await probe("callTool", "create_payment_quote", {});
r = await last();
check(!r.ok, `the host refused a model-only tool from a card (${r.error})`);
await probe("callTool", "approve_quote", { quote_id: "qt-someone-elses", approval_token: token, displayed_amount_kobo: 1 });
r = await last();
check(!r.ok, `the host refused a quote this chat has no card for (${r.error})`);
await probe("callTool", "no_such_tool", {});
r = await last();
check(!r.ok, `the host refused an unknown tool (${r.error})`);

await probe("openLink", "https://example.com/pay");
// A new tab starts at about:blank and shows the link once its navigation commits, which takes as long as the
// network does: the check waits for that, up to five seconds.
const opened = () => context.pages().some((p) => p.url().startsWith("https://example.com"));
for (let i = 0; i < 50 && !opened(); i += 1) await page.waitForTimeout(100);
check(opened(), "ui/open-link opened a web link in a new tab");
await probe("openLink", "javascript:alert(1)");
r = await last();
check(r.ok && r.value.isError === true, "ui/open-link refused a non-web link");

await probe("context", "Card shows: waiting for checkout");
check(await seen(page.getByText("Card: Card shows: waiting for checkout").waitFor({ timeout: 5000 })), "ui/update-model-context is kept and shown as a short card note");
await probe("message", "Is this the right amount?");
check(await seen(page.getByText("Is this the right amount?").waitFor({ timeout: 8000 })), "ui/message puts the card's words in the transcript, as the card's");
check(await seen(page.getByText("I can't do that").waitFor({ timeout: 15000 })), "and starts a model turn, whose reply arrives over the stream");

const requests = (await modelRequests()).filter((q) => q.tools);
const model = requests.at(-1).messages;
const texts = model.map((m) => `${m.role}: ${typeof m.content === "string" ? m.content : ""}`);
check(texts.some((t) => t.startsWith("user: [card message] Is this the right amount?")), "the model saw the card's message, labelled [card message]");
check(texts.some((t) => t.startsWith("user: [card update] Card shows: waiting for checkout")), "the model saw the card's note, labelled [card update]");
const wire = JSON.stringify(model);
check(!wire.includes(token) && !wire.includes("approvalToken") && !wire.includes("/sim/checkout/"), "the approval token and the checkout link never entered the model's context");
check(!wire.includes("approve_quote") && !wire.includes("verify_quote"), "the card's own tool calls are not in the model's context");
// The three refused calls above are 403s the browser logs as failed loads.
const unexpected = errors.filter((e) => !/Failed to load resource: the server responded with a status of 403/.test(e));
check(unexpected.length === 0, `no page errors ${unexpected.join("; ")}`);
await chromium.close();
finish();
