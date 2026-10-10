// SPDX-License-Identifier: AGPL-3.0-or-later
// Shows each card state in a sandboxed iframe on the official AppBridge and, per mode:
//   shots   screenshots the card in light and dark into docs/screens (card-<connector>-<state>-<scheme>.png,
//           react-<connector>-<state>-<scheme>.png for the unchanged React card)
//   checks  interaction, accessibility and contrast checks of the Python-side card
//   live    the card against running Workers: checkout, one-time code, payouts refused, order tracker
//           (PLAIN/OTP/NOPAY urls as in card-states-capture.mjs; PLAIN needs a small FOOD_STEP_SECONDS)
//
// usage: node conformance/card-states.mjs shots|checks|live [--card python|react|both] [--only <regex>] [--schemes light,dark]
// The QuoteViews are the ones recorded by card-states-capture.mjs (card-states.fixtures.json); a few
// states that need a hostile input (a long name) or a clock (a transfer in flight) are derived from them below.
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { readFile, writeFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { chromium } from "playwright";
import { contrastReport, hostPageHtml, settle } from "./card-checks.mjs";

const here = fileURLToPath(new URL(".", import.meta.url));
const root = fileURLToPath(new URL("../", import.meta.url));
const CARDS = {
  python: { prefix: "card", file: `${root}checkout/src/checkout/card/card.html` },
  react: { prefix: "react", file: `${root}checkout/src/checkout/card/react-card.html` },
};
const PORT = Number(process.env.STATES_PORT ?? 8893);
const args = process.argv.slice(2);
const mode = args[0] ?? "shots";
const option = (name, fallback) => (args.includes(`--${name}`) ? args[args.indexOf(`--${name}`) + 1] : fallback);
const which = option("card", mode === "checks" ? "python" : "both");
const only = new RegExp(option("only", "."));
const schemes = option("schemes", "light,dark").split(",");

const fixtures = JSON.parse(await readFile(`${here}card-states.fixtures.json`, "utf8"));
const copy = (name) => structuredClone(fixtures[name]);
function derive(base, patch) {
  const view = copy(base);
  patch(view.structuredContent.quote, view);
  return view;
}

const LONG_NAME = "ADEWALE CHUKWUEMEKA OLUWASEUN-ABUBAKAR OKONKWO-BELLO";
const LONG_PLAN = "MTN 1.5GB Monthly Data Bundle with 500MB Night Plan - 30 days";
Object.assign(fixtures, {
  "transfer/processing": derive("transfer/succeeded", (q) => {
    Object.assign(q, { phase: "processing", receipt: null, message: "Working on it.", poll: true });
  }),
  "transfer/long-name": derive("transfer/approve", (q) => {
    q.details.recipientName = LONG_NAME;
    q.merchant = LONG_NAME;
    q.details.bankName = "Guaranty Trust Bank Limited (Nigeria)";
  }),
  "data/long-plan": derive("data/approve", (q) => {
    q.details.plan = LONG_PLAN;
    q.details.readBack = `${LONG_PLAN} on MTN to 0801 111 1111 for ${q.amount.display}`;
  }),
  "data/processing": derive("airtime/processing", (q) => {
    q.description = "MTN data";
    q.details = { kind: "data", network: "MTN", plan: "N1000 1.5GB - 30 days", phone: "201000000000", readBack: "" };
  }),
  "food/long-lines": derive("food/approve-many", (q) => {
    q.details.lines[1].name = "Fried rice, dodo, grilled chicken and a very long extra side of peppered snail";
  }),
});

fixtures["transfer/expiring"] = copy("transfer/approve");
fixtures["transfer/expired"] = derive("transfer/approve", (q) => {
  Object.assign(q, { phase: "expired", message: "Quote expired. Ask for a new one." });
});
fixtures["transfer/gone"] = derive("transfer/approve", (q) => {
  Object.assign(q, { phase: "gone", poll: false });
});
fixtures["airtime/approve-wallet"] = derive("airtime/approve", (q) => {
  q.wallet = { balanceKobo: 200000, balance: "₦2,000" };
});
fixtures["airtime/failed"] = derive("airtime/checkout", (q) => {
  Object.assign(q, { phase: "failed", checkoutUrl: null, message: "Payment failed. Nothing was charged." });
});

// Recorded quotes are long expired; a card shows a live quote until a minute before it lapses.
const EXPIRES_IN = { "transfer/expiring": 45_000 };
const refreshed = (key, view) => {
  const quote = { ...view.structuredContent.quote, expiresAt: new Date(Date.now() + (EXPIRES_IN[key] ?? 300_000)).toISOString() };
  return { ...view, structuredContent: { quote } };
};

const CONNECTOR_OF = { transfer: "transfer", airtime: "airtime", data: "airtime", food: "food" };
const nameOf = (key) => {
  const [group, ...rest] = key.split("/");
  return `${CONNECTOR_OF[group] ?? group}-${group === "data" ? "data-" : ""}${rest.join("-")}`;
};

const bundle = await build({
  entryPoints: [`${here}card-states-page.mjs`], bundle: true, format: "esm", write: false, minify: true, platform: "browser",
});
const html = await hostPageHtml();
const server = createServer(async (req, res) => {
  const path = new URL(req.url, "http://x").pathname;
  const card = /^\/card\/(\w+)$/.exec(path)?.[1];
  if (path === "/") res.writeHead(200, { "content-type": "text/html" }).end(html);
  else if (path === "/card-states-page.js") res.writeHead(200, { "content-type": "text/javascript" }).end(bundle.outputFiles[0].text);
  else if (card && CARDS[card]) res.writeHead(200, { "content-type": "text/html" }).end(await readFile(CARDS[card].file));
  else res.writeHead(404).end();
}).listen(PORT);

const browser = await chromium.launch();
async function open(cardName, key, scheme, extra = {}) {
  const context = await browser.newContext({ colorScheme: scheme, viewport: { width: 400, height: 900 }, deviceScaleFactor: 2, reducedMotion: "reduce" });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  await page.goto(`http://localhost:${PORT}/`);
  const cardHtml = await (await fetch(`http://localhost:${PORT}/card/${cardName}`)).text();
  const { notice, ...result } = refreshed(key, fixtures[key]);
  await page.evaluate((a) => window.__mount(a), { html: cardHtml, result, scheme, notice, ...extra });
  await settle(page);
  await page.waitForTimeout(150);
  return { page, context, errors, frame: page.frameLocator("#card") };
}

// A palette PNG keeps flat UI screenshots small; without pngquant the full-colour file stays.
const shrink = (file) => {
  try {
    execFileSync("pngquant", ["--force", "--skip-if-larger", "--quality", "70-95", "--output", file, file], { stdio: "ignore" });
  } catch {}
};

async function shots() {
  const failures = [];
  for (const cardName of which === "both" ? ["python", "react"] : [which]) {
    // The React card shows a refusal only as the reply to its own tools/call, so a pushed refusal is not its state.
    for (const key of Object.keys(fixtures).sort().filter((k) => only.test(k) && !(cardName === "react" && fixtures[k].notice))) {
      for (const scheme of cardName === "react" ? ["light"] : schemes) {
        const file = `${root}docs/screens/${CARDS[cardName].prefix}-${nameOf(key)}-${scheme}.png`;
        const { page, context, errors } = await open(cardName, key, scheme);
        const height = await page.evaluate(() => window.__height);
        const png = await page.locator("#card").screenshot();
        await writeFile(file, png);
        shrink(file);
        const blank = await page.frameLocator("#card").locator("body").innerText();
        console.log(`${cardName.padEnd(6)} ${key.padEnd(24)} ${scheme.padEnd(5)} ${String(height).padStart(4)}px ${String(Math.round(png.length / 1024)).padStart(3)} KB ${blank.trim() ? "" : "BLANK "}${errors.join("; ")}`);
        if (!blank.trim() || errors.length) failures.push(`${cardName} ${key} ${scheme}`);
        await context.close();
      }
    }
  }
  return failures;
}

let failed = 0;
const check = (ok, what) => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${what}`);
  if (!ok) failed += 1;
};
const calls = (page) => page.evaluate(() => window.__log.filter((e) => e.kind === "calltool").map((e) => ({ name: e.name, args: e.args })));

async function focusOrder(page, frame, presses) {
  const names = [];
  for (let i = 0; i < presses; i += 1) {
    await page.keyboard.press("Tab");
    names.push(await frame.locator(":focus").evaluate((el) => (el.getAttribute("aria-label") || el.labels?.[0]?.textContent || el.textContent || el.id || el.tagName).trim().slice(0, 30), undefined, { timeout: 1500 }).catch(() => null));
  }
  return names;
}

async function checks() {
  for (const scheme of schemes) {
    console.log(`\ncontrast and errors, ${scheme}`);
    for (const key of Object.keys(fixtures).sort().filter((k) => only.test(k))) {
      const { page, context, errors, frame } = await open("python", key, scheme);
      const low = await frame.locator("body").evaluate(`(${contrastReport.toString()})()`);
      check(low.length === 0 && errors.length === 0, `${key}: text passes WCAG AA${low.length ? ` (${JSON.stringify(low.slice(0, 3))})` : ""}${errors.length ? ` errors ${errors}` : ""}`);
      const unnamed = await frame.locator("button, input").evaluateAll((els) => els.filter((el) => !(el.getAttribute("aria-label") || el.labels?.[0]?.textContent || el.textContent).trim()).length);
      check(unnamed === 0, `${key}: every button and input has an accessible name`);
      await context.close();
    }
  }

  console.log("\nApprove, Decline and a correction: no tick");
  for (const key of ["airtime/approve", "data/approve", "data/long-plan", "transfer/approve", "food/approve"]) {
    const { page, context, frame } = await open("python", key, "light", { answer: copy("airtime/checkout") });
    const approve = frame.getByRole("button", { name: "Approve" });
    check((await frame.getByRole("checkbox").count()) === 0 && (await approve.isEnabled()), `${key}: no tick, and Approve is enabled`);
    await approve.click();
    await page.waitForTimeout(300);
    const sent = (await calls(page)).find((c) => c.name === "approve_quote");
    check(sent?.args.readback_confirmed === true, `${key}: approve_quote carried readback_confirmed: true`);
    await context.close();
  }

  console.log("\npaying from the wallet");
  for (const key of ["airtime/approve", "transfer/approve", "food/approve"]) {
    const { context, frame } = await open("python", key, "light");
    check((await frame.getByRole("button", { name: /Pay from wallet/ }).count()) === 0, `${key}: no wallet offered when the quote carries none`);
    await context.close();
  }
  {
    const { page, context, frame } = await open("python", "airtime/approve-wallet", "light", { answer: copy("airtime/succeeded") });
    const pay = frame.getByRole("button", { name: "Pay from wallet (₦2,000)" });
    check((await pay.count()) === 1 && (await pay.isEnabled()), "the wallet is offered with its balance");
    await pay.click();
    await frame.getByText("Airtime delivered").first().waitFor({ timeout: 5000 });
    const sent = (await calls(page)).find((c) => c.name === "approve_quote");
    check(sent?.args.funding === "wallet" && sent.args.readback_confirmed === true, "approve_quote carried funding: wallet");
    check(!(await page.evaluate(() => window.__log.some((e) => e.kind === "openlink"))), "and no checkout was opened");
    await context.close();
  }
  {
    const { page, context, frame } = await open("python", "airtime/approve-wallet", "light", { answer: copy("airtime/checkout") });
    await frame.getByRole("button", { name: "Approve" }).click();
    await page.waitForTimeout(300);
    const sent = (await calls(page)).find((c) => c.name === "approve_quote");
    check(sent && !("funding" in sent.args), "Approve beside it sends no funding: the checkout as before");
    await context.close();
  }
  for (const [code, text] of [
    ["WALLET_SHORT", "The wallet holds ₦200, less than this quote's ₦500. Nothing was taken."],
    ["WALLET_FROZEN", "This wallet is frozen, so it cannot pay. Nothing was taken."],
  ]) {
    const refused = { isError: true, content: [{ type: "text", text: `${code}: ${text}` }] };
    const { context, frame } = await open("python", "airtime/approve-wallet", "light", { answer: refused });
    await frame.getByRole("button", { name: /Pay from wallet/ }).click();
    const notice = frame.getByRole("alert");
    await notice.getByText(text).waitFor({ timeout: 5000 });
    check((await notice.innerText()).trim() === text, `${code}: the reason alone on the card, without the code`);
    check((await frame.getByRole("button", { name: /Pay from wallet/ }).count()) === 1, `${code}: and the card still offers its choices`);
    await context.close();
  }

  console.log("\ncorrection: declines the card and tells the chat");
  for (const key of ["airtime/approve", "transfer/approve"]) {
    const { page, context, frame } = await open("python", key, "light", { answer: copy("airtime/checkout") });
    const field = frame.getByRole("textbox", { name: "Correction" });
    check((await field.count()) === 1, `${key}: one field named Correction, already open`);
    await field.click();
    await field.fill("make it 2000 naira");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(400);
    check((await calls(page)).some((c) => c.name === "decline_quote"), `${key}: the card is declined`);
    check(await page.evaluate(() => window.__log.some((e) => e.kind === "message" && /^Correction to the card for .+₦.+: make it 2000 naira\. That card is declined: quote it again with this change\.$/.test(e.detail))), `${key}: the note reached the chat with the order it corrects`);
    await context.close();
  }
  {
    const { page, context, frame } = await open("python", "airtime/approve", "light");
    await frame.getByRole("button", { name: "Send correction" }).click();
    await page.waitForTimeout(300);
    check(!(await calls(page)).some((c) => c.name === "decline_quote"), "an empty correction does nothing");
    await context.close();
  }

  console.log("\na quote the connector does not know (the chat moved to an account)");
  for (const key of ["transfer/approve", "airtime/approve"]) {
    const lost = { isError: true, content: [{ type: "text", text: "QUOTE_NOT_FOUND: There is no quote qt-gone." }] };
    const { page, context, frame, errors } = await open("python", key, "light", { answer: lost });
    await frame.getByRole("button", { name: "Approve" }).click();
    await frame.getByText("No longer available").waitFor({ timeout: 5000 });
    const text = await frame.locator("body").innerText();
    check(!/QUOTE_NOT_FOUND|no quote/i.test(text), `${key}: the card says it is over, not the connector's error (${JSON.stringify(text.slice(0, 80))})`);
    check((await frame.getByRole("button").count()) === 0, `${key}: and offers nothing to press`);
    check((await calls(page)).filter((c) => c.name === "approve_quote").length === 1 && errors.length === 0, `${key}: one call was made, no page error`);
    await context.close();
  }

  console.log("\nkeyboard");
  for (const [key, expected] of [
    ["transfer/approve", ["Approve", "Decline"]],
    ["airtime/approve", ["Approve", "Decline", "Correction"]],
    ["airtime/approve-wallet", ["Approve", "Pay from wallet", "Decline", "Correction"]],
    ["airtime/checkout", ["Open checkout", "I closed it"]],
    ["transfer/otp", ["One-time code", "Confirm"]],
  ]) {
    const { page, context, frame } = await open("python", key, "light");
    const order = await focusOrder(page, frame, expected.length);
    check(expected.every((want, i) => (want instanceof RegExp ? want.test(order[i] ?? "") : (order[i] ?? "").startsWith(want))), `${key}: Tab order ${JSON.stringify(order)}`);
    const ring = await frame.locator(":focus").evaluate((el) => {
      const s = getComputedStyle(el);
      return s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2;
    }, undefined, { timeout: 1500 }).catch(() => false);
    check(ring, `${key}: the focused control shows a focus ring`);
    await context.close();
  }

  console.log("\nOTP form");
  {
    const { page, context, frame } = await open("python", "transfer/otp", "light", { answer: copy("transfer/succeeded") });
    await frame.getByLabel("Code").fill("123456");
    await frame.getByRole("button", { name: "Confirm" }).click();
    await page.waitForTimeout(300);
    const sent = (await calls(page)).find((c) => c.name === "submit_otp");
    if (!sent) console.log("   calls:", JSON.stringify(await calls(page)));
    check(sent?.args.otp === "123456", "submit_otp carried the typed code");
    check((await frame.getByText("Transfer sent").count()) > 0, "the card showed the receipt from the answer");
    await context.close();
  }
  {
    const { page, context, frame } = await open("python", "transfer/otp", "light", { answer: copy("transfer/succeeded") });
    await frame.getByLabel("Code").fill("654321");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(300);
    check((await calls(page)).some((c) => c.name === "submit_otp" && c.args.otp === "654321"), "Enter in the code field sends the code (the sandbox allows no form submission)");
    await context.close();
  }
  {
    const { context, frame } = await open("python", "transfer/otp-rejected", "light");
    check((await frame.getByRole("alert").innerText()).trim().length > 0, "a rejected code shows in an alert");
    await context.close();
  }
}


// ---- live: the card wired through the bridge to running Workers -------------------------------------
const WORKERS = {
  plain: process.env.PLAIN ?? "http://localhost:8890",
  otp: process.env.OTP ?? "http://localhost:8891",
  nopay: process.env.NOPAY ?? "http://localhost:8892",
};
let rpcId = 0;
const rpc = async (base, connector, name, args) => {
  const body = { jsonrpc: "2.0", id: ++rpcId, method: "tools/call", params: { name, arguments: args } };
  const res = await fetch(`${base}/${connector}/mcp`, { method: "POST", headers: { "content-type": "application/json", accept: "application/json" }, body: JSON.stringify(body) });
  return (await res.json()).result;
};
const runKey = Math.random().toString(36).slice(2, 8);

async function openLive(base, connector, tool, args) {
  const made = await rpc(base, connector, tool, { ...args, idempotency_key: `live-${runKey}-${++rpcId}` });
  if (made.isError) throw new Error(`${connector} refused the quote: ${made.content?.[0]?.text}`);
  const context = await browser.newContext({ colorScheme: "light", viewport: { width: 400, height: 900 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.exposeFunction("__forward", (name, callArgs) => rpc(base, connector, name, callArgs));
  await page.goto(`http://localhost:${PORT}/`);
  const cardHtml = await (await fetch(`http://localhost:${PORT}/card/python`)).text();
  await page.evaluate((a) => window.__mount(a), { html: cardHtml, result: made, scheme: "light" });
  await settle(page);
  return { page, context, errors, frame: page.frameLocator("#card"), made };
}
const shows = (frame, text, ms = 15000) => frame.getByText(text).first().waitFor({ timeout: ms }).then(() => true, () => false);
const paySim = (base, page) =>
  page.evaluate(() => window.__log.find((e) => e.kind === "openlink")?.url).then((url) => fetch(`${base}${new URL(url).pathname}/pay`, { method: "POST" }));

async function live() {
  console.log("airtime: Approve, checkout, delivered");
  {
    const { page, context, errors, frame } = await openLive(WORKERS.plain, "airtime", "create_airtime_quote", { network: "mtn", phone: "08011111111", amount_kobo: 50_000, amount_as_user_said: "N500" });
    await frame.getByRole("button", { name: "Approve" }).click();
    check(await shows(frame, "Open checkout"), "the server accepted the approval and moved to checkout");
    check(await page.evaluate(() => window.__log.some((e) => e.kind === "openlink")), "the card asked the host to open the checkout");
    await paySim(WORKERS.plain, page);
    check(await shows(frame, "Airtime delivered"), "polling ended on the delivered receipt");
    check(errors.length === 0, `no page errors ${errors}`);
    await context.close();
  }
  console.log("airtime: refund due");
  {
    const { page, context, frame } = await openLive(WORKERS.plain, "airtime", "create_airtime_quote", { network: "mtn", phone: "100000000000", amount_kobo: 50_000, amount_as_user_said: "N500" });
    await frame.getByRole("button", { name: "Approve" }).click();
    await shows(frame, "Open checkout");
    await paySim(WORKERS.plain, page);
    check(await shows(frame, "Refund due"), "a paid order VTpass could not deliver shows Refund due");
    await context.close();
  }
  console.log("transfer with a one-time code");
  {
    const { frame, context } = await openLive(WORKERS.otp, "send-money", "create_transfer_quote", { account_number: "0000000000", bank_code: "057", amount_kobo: 2_500_000, amount_as_user_said: "25k", narration: "Rent share" });
    await frame.getByRole("button", { name: "Approve" }).click();
    check(await shows(frame, "Confirm"), "approval moved the card to the code step");
    await frame.getByLabel("One-time code").fill("000000");
    await frame.getByRole("button", { name: "Confirm" }).click();
    check(await frame.getByRole("alert").waitFor({ timeout: 8000 }).then(() => true, () => false), "a wrong code shows an alert");
    check(await frame.getByLabel("One-time code").evaluate((el) => el === el.getRootNode().activeElement), "the field is focused again for the next try");
    const hint = await frame.getByText(/Simulated code/).innerText();
    await frame.getByLabel("One-time code").fill(hint.match(/\d{4,}/)[0]);
    await frame.getByLabel("One-time code").press("Enter");
    check(await shows(frame, "Transfer sent", 8000), "the right code ended on the Transfer sent receipt");
    await context.close();
  }
  console.log("transfer on an account that cannot make payouts");
  {
    const { frame, context } = await openLive(WORKERS.nopay, "send-money", "create_transfer_quote", { account_number: "0000000000", bank_code: "057", amount_kobo: 2_500_000, amount_as_user_said: "25k" });
    await frame.getByRole("button", { name: "Approve" }).click();
    check(await shows(frame, "Not sent", 8000), "the unavailable state shows Not sent with the reason");
    check((await frame.getByRole("button").count()) === 0, "there is no button left to press");
    await context.close();
  }
  console.log("food order to delivery");
  {
    const { page, context, frame } = await openLive(WORKERS.plain, "food-order", "create_food_quote", { items: [{ item_id: "beef-suya", quantity: 1 }], delivery_area: "Surulere" });
    await frame.getByRole("button", { name: "Approve" }).click();
    await shows(frame, "Open checkout");
    await paySim(WORKERS.plain, page);
    check(await shows(frame, "Order accepted", 10000), "the tracker appeared after payment");
    check(await frame.locator('[aria-current="step"]').count() === 1, "exactly one step is marked current");
    check(await shows(frame, "Order delivered", 40000), "the tracker ended on the Order delivered receipt");
    await context.close();
  }
}

try {
  const failures = mode === "checks" ? await checks() : mode === "live" ? await live() : await shots();
  if (failures?.length) failed += failures.length;
} finally {
  await browser.close();
  server.close();
}
if (mode !== "shots") console.log(failed === 0 ? "\nAll checks passed." : `\n${failed} check(s) failed.`);
process.exit(failed === 0 ? 0 : 1);
