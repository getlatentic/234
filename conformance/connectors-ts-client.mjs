// SPDX-License-Identifier: AGPL-3.0-or-later
// Drives all four connectors of the Python Worker with the official TypeScript MCP client over Streamable
// HTTP, as a host would: the handshake, tools/list with MCP Apps metadata (read by the ext-apps helpers), a full
// quote-approve-pay-verify path for each connector, and the refusals a host must be able to rely on.
//
// usage: node conformance/connectors-ts-client.mjs   (Worker on CHECKOUT_URL, default http://localhost:8787,
//        started with ENABLE_TEST_ROUTES=1 so the run can start from an empty ledger)
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import { getToolUiResourceUri, isToolVisibilityAppOnly, isToolVisibilityModelOnly } from "@modelcontextprotocol/ext-apps/app-bridge";

const WORKER = process.env.CHECKOUT_URL ?? "http://localhost:8787";
let failed = 0;
const check = (ok, what) => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${what}`);
  if (!ok) failed += 1;
};

await fetch(`${WORKER}/test/reset`, { method: "POST" });

// `owner` is the key the chat host names in the owner header, on every request the client sends.
async function connect(name, owner) {
  const client = new Client({ name: "ts-client-conformance", version: "0.1.0" });
  const requestInit = owner ? { headers: { "x-ledger-owner": owner } } : undefined;
  await client.connect(new StreamableHTTPClientTransport(new URL(`${WORKER}/${name}/mcp`), { requestInit }));
  return client;
}

const text = (result) => result.content?.[0]?.text ?? "";
const quoteOf = (result) => result.structuredContent?.quote;
const call = (client, name, args) => client.callTool({ name, arguments: args });
const tokenOf = (made) => made._meta?.approvalToken;

async function payOnTheSimulatedCheckout(url) {
  const reference = url.split("/").at(-1);
  await fetch(`${WORKER}/sim/checkout/${reference}`);
  const page = await fetch(`${WORKER}/sim/checkout/${reference}/pay`, { method: "POST" });
  return page.status === 200;
}

const approval = (made, extra = {}) => ({
  quote_id: quoteOf(made).id,
  approval_token: tokenOf(made),
  displayed_amount_kobo: quoteOf(made).amount.kobo,
  ...extra,
});

async function checkSurface(name, expectedModelTools) {
  const client = await connect(name);
  console.log(`\n${name}`);
  const version = client.getServerVersion();
  check(version?.name === name, `initialize named the server ${name}`);
  check((client.getInstructions() ?? "").includes("You cannot approve anything"), "instructions tell the model it cannot approve");
  const { tools } = await client.listTools();
  const modelTools = tools.filter((t) => !isToolVisibilityAppOnly(t)).map((t) => t.name).sort();
  check(JSON.stringify(modelTools) === JSON.stringify([...expectedModelTools, "get_quote_status"].sort()), `the model is offered exactly: ${modelTools.join(", ")}`);
  const cardTools = tools.filter(isToolVisibilityAppOnly).map((t) => t.name);
  check(["approve_quote", "verify_quote", "decline_quote"].every((n) => cardTools.includes(n)), `the card's tools are app-only: ${cardTools.join(", ")}`);
  check(!modelTools.includes("order_from_menu"), "no app-only tool is among the model's");
  const quoteTool = tools.find((t) => t.name.startsWith("create_") && t.name.endsWith("_quote"));
  check(isToolVisibilityModelOnly(quoteTool) && getToolUiResourceUri(quoteTool) === `ui://${name}/card.html`, "the quote tool is model-only and names the card");
  const card = await client.readResource({ uri: `ui://${name}/card.html` });
  check(card.contents[0].mimeType === "text/html;profile=mcp-app" && card.contents[0].text.includes("<html"), "the card is served as an MCP App resource");
  const mode = JSON.parse((await client.readResource({ uri: "paystack-demo://mode" })).contents[0].text);
  check(mode.connector === name && mode.simulated === true, `the mode banner says ${mode.label}`);
  return client;
}

// paystack-pay
{
  const client = await checkSurface("paystack-pay", ["create_payment_quote"]);
  const made = await call(client, "create_payment_quote", {
    amount_kobo: 250_000, amount_as_user_said: "two thousand five hundred naira", description: "Lunch", merchant: "Demo Kitchen", idempotency_key: "ts-pay-00000001",
  });
  check(quoteOf(made)?.phase === "awaiting_approval" && /^[0-9a-f]{64}$/.test(tokenOf(made)) && !text(made).includes(tokenOf(made)), "quote made; the approval token is in _meta only");
  const denied = await call(client, "approve_quote", approval(made, { approval_token: "not-the-token" }));
  check(denied.isError === true && text(denied).startsWith("APPROVAL_DENIED"), "approval without the card's token is refused");
  const approved = await call(client, "approve_quote", approval(made));
  check(quoteOf(approved).phase === "awaiting_checkout", "approved with the card's token");
  check(await payOnTheSimulatedCheckout(quoteOf(approved).checkoutUrl), "paid on the simulated checkout page");
  const done = await call(client, "verify_quote", { quote_id: quoteOf(made).id });
  check(quoteOf(done).phase === "succeeded" && quoteOf(done).receipt.title === "Payment received", "verified to a receipt");
  const status = await call(client, "get_quote_status", { quote_id: quoteOf(made).id });
  check(quoteOf(status).checkoutUrl === null && !JSON.stringify(status).includes("sim/checkout"), "the model's status result carries no checkout link");
  await client.close();
}

// send-money
{
  const client = await checkSurface("send-money", ["create_transfer_quote"]);
  const made = await call(client, "create_transfer_quote", {
    account_number: "0000000000", bank_code: "057", amount_kobo: 2_500_000, amount_as_user_said: "25k", narration: "Rent", idempotency_key: "ts-send-00000001",
  });
  check(quoteOf(made).details.recipientName === "PAYSTACK TEST ACCOUNT" && !text(made).includes("0000000000"), "the recipient's name comes from the bank lookup; the account number stays out of the model's text");
  const done = await call(client, "approve_quote", approval(made));
  check(quoteOf(done).phase === "succeeded" && quoteOf(done).receipt.title === "Transfer sent", "approved and sent");
  const again = await call(client, "approve_quote", approval(made));
  check(quoteOf(again).phase === "succeeded" && JSON.stringify(quoteOf(again).receipt) === JSON.stringify(quoteOf(done).receipt), "a repeated approval returns the same receipt");
  const named = (bank, extra = {}) => ({ account_number: "0123456789", amount_kobo: 500_000, amount_as_user_said: "5k", bank, ...extra });
  const byName = await call(client, "create_transfer_quote", named("GTB", { idempotency_key: "ts-bank-00000001" }));
  check(quoteOf(byName)?.details.bankName === "Guaranty Trust Bank", "a bank named the way people say it is resolved by the connector, and the card gets the bank's name");
  const unknown = await call(client, "create_transfer_quote", named("Acess Bank", { idempotency_key: "ts-bank-00000002" }));
  check(unknown.isError === true && text(unknown).startsWith("BANK_UNKNOWN") && text(unknown).includes("Access Bank"), "an unknown bank is refused and the nearest bank is named");
  const several = await call(client, "create_transfer_quote", named("First", { idempotency_key: "ts-bank-00000003" }));
  check(several.isError === true && text(several).startsWith("BANK_AMBIGUOUS") && text(several).includes("First Bank of Nigeria"), "a name that fits several banks is refused, naming some");
  const contradicted = await call(client, "create_transfer_quote", named("GTB", { bank_code: "044", idempotency_key: "ts-bank-00000004" }));
  check(contradicted.isError === true && text(contradicted).startsWith("BANK_MISMATCH"), "a bank code that contradicts the bank named is refused");
  const byCode = await call(client, "create_transfer_quote", named(undefined, { bank_code: "058", idempotency_key: "ts-bank-00000005" }));
  check(quoteOf(byCode)?.details.bankName === "Guaranty Trust Bank", "a client that sends only the bank code (the TypeScript contract) still gets its quote");
  await client.close();
}

// airtime
{
  const client = await checkSurface("airtime", ["create_airtime_quote", "create_data_quote", "list_data_plans"]);
  const plans = await call(client, "list_data_plans", { network: "mtn" });
  check(text(plans).includes("mtn-10mb-100: N100 100MB - 24 hrs, ₦100"), "data plans listed");
  const made = await call(client, "create_airtime_quote", {
    network: "mtn", phone: "08011111111", amount_kobo: 50_000, amount_as_user_said: "five hundred naira", idempotency_key: "ts-air-000000001",
  });
  check(text(made).includes('"₦500 MTN airtime to 0801 111 1111"'), "the model is told to read the number and amount back");
  const noReadback = await call(client, "approve_quote", approval(made));
  check(noReadback.isError === true && text(noReadback).startsWith("READBACK_REQUIRED"), "approval without the read-back confirmation is refused");
  const approved = await call(client, "approve_quote", approval(made, { readback_confirmed: true }));
  check(await payOnTheSimulatedCheckout(quoteOf(approved).checkoutUrl), "paid on the simulated checkout page");
  const done = await call(client, "verify_quote", { quote_id: quoteOf(made).id });
  check(quoteOf(done).phase === "succeeded" && quoteOf(done).receipt.title === "Airtime delivered", "delivered after the confirmed payment");
  const unknown = await call(client, "create_airtime_quote", { network: "vodafone", phone: "08011111111", amount_kobo: 50_000, amount_as_user_said: "500", idempotency_key: "ts-air-000000002" });
  check(unknown.isError === true, "an unknown network is refused");
  await client.close();
}

// food-order
{
  const client = await checkSurface("food-order", ["search_menu", "build_basket", "create_food_quote"]);
  const search = await call(client, "search_menu", { query: "suya" });
  check(text(search).includes("simulated merchant (not Chowdeck)") && !text(search).includes("\n") && !text(search).includes("Beef suya"), "the model is told in one line that the merchant is simulated, and none of the items");
  const { tools } = await client.listTools();
  const searchTool = tools.find((t) => t.name === "search_menu");
  const orderTool = tools.find((t) => t.name === "order_from_menu");
  check(isToolVisibilityModelOnly(searchTool) && getToolUiResourceUri(searchTool) === "ui://food-order/menu.html", "search_menu is model-only and names the menu view");
  check(isToolVisibilityAppOnly(orderTool) && getToolUiResourceUri(orderTool) === "ui://food-order/menu.html", "order_from_menu is app-only and belongs to the menu view");
  const view = await client.readResource({ uri: "ui://food-order/menu.html" });
  check(view.contents[0].mimeType === "text/html;profile=mcp-app" && view.contents[0].text.includes("order_from_menu") && view.contents[0]._meta?.ui?.prefersBorder === false, "the menu view is served as an MCP App resource");
  const menuData = search.structuredContent;
  check(menuData.items.length === 1 && menuData.items[0].price_kobo === 350_000 && menuData.items[0].available === true && menuData.areas.includes("Yaba") && /^[0-9a-f]{32}$/.test(menuData.card_id), "the card is given the item, its price in kobo, availability, the areas and its own id");
  const ordered = await call(client, "order_from_menu", { card_id: menuData.card_id, items: [{ item_id: "beef-suya", quantity: 2 }], delivery_area: "Maryland" });
  check(quoteOf(ordered).amount.kobo === 2 * 350_000 + 120_000 && ordered._meta?.ui?.resourceUri === "ui://food-order/card.html" && !text(ordered).includes(tokenOf(ordered)), "the app-only order is priced by the server, opens the approval card and keeps the token out of the text");
  const priced = await call(client, "order_from_menu", { card_id: "d".repeat(32), items: [{ item_id: "beef-suya", quantity: 1, price: 1 }], delivery_area: "Yaba" });
  check(priced.isError === true, "a price sent by the card is refused");
  const made = await call(client, "create_food_quote", { items: [{ item_id: "zobo", quantity: 2 }], delivery_area: "Yaba", idempotency_key: "ts-food-00000001" });
  check(quoteOf(made).amount.display === "₦2,800" && quoteOf(made).mode.label.startsWith("Simulated merchant: not Chowdeck"), "the server prices the basket and labels the merchant");
  const approved = await call(client, "approve_quote", approval(made));
  check(await payOnTheSimulatedCheckout(quoteOf(approved).checkoutUrl), "paid on the simulated checkout page");
  const accepted = await call(client, "verify_quote", { quote_id: quoteOf(made).id });
  check(quoteOf(accepted).phase === "processing" && quoteOf(accepted).tracking?.current === 0, "the kitchen accepted the paid order");
  await client.close();
}

// the smallest amount: no connector makes a quote for one kobo, whoever asks and however it is worded
{
  console.log("\nthe smallest amount");
  const tools = {
    "paystack-pay": ["create_payment_quote", { description: "Lunch", merchant: "Demo" }],
    "send-money": ["create_transfer_quote", { account_number: "0123456789", bank: "GTB" }],
    airtime: ["create_airtime_quote", { network: "mtn", phone: "08011111111" }],
  };
  for (const [connector, [tool, args]] of Object.entries(tools)) {
    const client = await connect(connector);
    const refused = await call(client, tool, { ...args, amount_kobo: 1, amount_as_user_said: "1 kobo", idempotency_key: `ts-floor-${connector}` });
    check(refused.isError === true && !refused.structuredContent && text(refused).startsWith("AMOUNT_TOO_SMALL: The smallest amount is ₦50."), `${connector}: one kobo is refused with the smallest amount, and no card`);
    const both = await call(client, tool, { ...args, amount_kobo: 300_000, amount_as_user_said: "₦3,000 and 1 kobo", idempotency_key: `ts-two-${connector}` });
    check(both.isError === true && text(both).startsWith("AMOUNT_UNCLEAR"), `${connector}: words with two amounts are refused, whichever amount_kobo names`);
    const atTheFloor = await call(client, tool, { ...args, amount_kobo: 5_000, amount_as_user_said: "50", idempotency_key: `ts-floor-ok-${connector}` });
    check(quoteOf(atTheFloor)?.amount.display === "₦50", `${connector}: the smallest amount itself is quoted`);
    await client.close();
  }
}

// owners: each visitor's money is their own
{
  console.log("\nowners");
  const [alice, bob] = [await connect("paystack-pay", "a1".repeat(16)), await connect("paystack-pay", "b0".repeat(16))];
  const quoteArgs = (key) => ({ amount_kobo: 3_000_000, amount_as_user_said: "30k", description: "Lunch", merchant: "Demo", idempotency_key: key });
  const madeByAlice = await call(alice, "create_payment_quote", quoteArgs("ts-owner-shared-1"));
  const madeByBob = await call(bob, "create_payment_quote", quoteArgs("ts-owner-shared-1"));
  check(!madeByAlice.isError && !madeByBob.isError && quoteOf(madeByAlice).id !== quoteOf(madeByBob).id, "two owners can use one idempotency key and get two quotes");
  for (const [tool, args] of [["get_quote_status", { quote_id: quoteOf(madeByAlice).id }], ["verify_quote", { quote_id: quoteOf(madeByAlice).id }], ["approve_quote", approval(madeByAlice)], ["decline_quote", { quote_id: quoteOf(madeByAlice).id, approval_token: tokenOf(madeByAlice) }]]) {
    const refused = await call(bob, tool, args);
    check(refused.isError === true && text(refused).startsWith("QUOTE_NOT_FOUND"), `another owner cannot ${tool} a quote even with its id and token`);
  }
  check(quoteOf(await call(alice, "get_quote_status", { quote_id: quoteOf(madeByAlice).id })).phase === "awaiting_approval", "the quote is untouched");
  for (let i = 0; i < 3; i += 1) await call(alice, "approve_quote", approval(await call(alice, "create_payment_quote", quoteArgs(`ts-owner-day-${i}`))));
  const over = await call(alice, "create_payment_quote", quoteArgs("ts-owner-day-9"));
  check(text(over) === "LIMIT_DAILY: ₦30,000 would take today's approved total above the daily limit of ₦100,000 (₦10,000 left today).", "an owner at their daily limit is refused in one line, with their own remainder");
  const bobsNext = await call(bob, "create_payment_quote", quoteArgs("ts-owner-day-bob"));
  check(quoteOf(bobsNext).limits.remainingToday === "₦100,000" && quoteOf(await call(bob, "approve_quote", approval(bobsNext))).phase === "awaiting_checkout", "another owner still has their whole day");
  await alice.close();
  await bob.close();
}

// the stateless era (protocol revision 2026-07-28): a client pinned to it, which never sends `initialize`
{
  console.log("\nMCP 2026-07-28, pinned");
  const client = new Client({ name: "ts-client-conformance", version: "0.1.0" }, { versionNegotiation: { mode: { pin: "2026-07-28" } } });
  await client.connect(new StreamableHTTPClientTransport(new URL(`${WORKER}/paystack-pay/mcp`)));
  check(client.getServerVersion()?.name === "paystack-pay", "server/discover named the server");
  check(client.getServerCapabilities()?.extensions?.["io.modelcontextprotocol/ui"]?.mimeTypes?.includes("text/html;profile=mcp-app"), "and offered the MCP Apps extension");
  const { tools } = await client.listTools();
  const create = tools.find((t) => t.name === "create_payment_quote");
  check(getToolUiResourceUri(create) === "ui://paystack-pay/card.html" && tools.filter(isToolVisibilityAppOnly).length === 3, "tools/list carries the card's address and the app-only tools' visibility");
  const view = await client.readResource({ uri: "ui://paystack-pay/card.html" });
  check(view.contents[0].mimeType === "text/html;profile=mcp-app" && view.contents[0].text.includes("<html"), "resources/read serves the card");
  const made = await call(client, "create_payment_quote", { amount_kobo: 250_000, amount_as_user_said: "2500", description: "Lunch", merchant: "Demo", idempotency_key: "ts-modern-0001" });
  check(quoteOf(made).phase === "awaiting_approval" && tokenOf(made)?.length === 64 && !text(made).includes(tokenOf(made)), "a tool call runs, the approval token in _meta and not in the text");
  const approved = await call(client, "approve_quote", approval(made));
  check(quoteOf(approved).phase === "awaiting_checkout", "and so does the app-only approval");
  await client.close();
}

console.log(failed === 0 ? "\nAll checks passed." : `\n${failed} check(s) failed.`);
process.exit(failed === 0 ? 0 : 1);
