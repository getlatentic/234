// SPDX-License-Identifier: AGPL-3.0-or-later
// Drives the memory connector of the Python Worker with the official TypeScript MCP client over Streamable HTTP,
// as the chat host does: both owner headers on every request, which tools the model sees and which only a card or
// the page calls (read by the ext-apps helpers), a proposal that writes nothing, the card's Save with the token the
// model never sees, a recall as quoted data, a forget with its Undo, a saved recipient used by id in a transfer
// quote, and one account's notes out of another's reach.
//
// usage: node conformance/memory-ts-client.mjs   (Worker on CHECKOUT_URL, default http://localhost:8787,
//        started with ENABLE_TEST_ROUTES=1 so the run can start from an empty ledger)
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import { getToolUiResourceUri, isToolVisibilityAppOnly, isToolVisibilityModelOnly } from "@modelcontextprotocol/ext-apps/app-bridge";

const WORKER = process.env.CHECKOUT_URL ?? "http://localhost:8787";
const ALICE = "a1".repeat(16);
const BOB = "b0".repeat(16);
let failed = 0;
const check = (ok, what) => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${what}`);
  if (!ok) failed += 1;
};

await fetch(`${WORKER}/test/reset`, { method: "POST" });

async function connect(name, owner, notes = true) {
  const client = new Client({ name: "ts-memory-conformance", version: "0.1.0" });
  const headers = { "x-ledger-owner": owner, ...(notes ? { "x-memory-owner": owner } : {}) };
  await client.connect(new StreamableHTTPClientTransport(new URL(`${WORKER}/${name}/mcp`), { requestInit: { headers } }));
  return client;
}

const text = (result) => result.content?.[0]?.text ?? "";
const call = (client, name, args) => client.callTool({ name, arguments: args });
const decision = (made, extra = {}) => ({ proposal_id: made.structuredContent.proposal_id, confirm_token: made._meta.confirmToken, ...extra });
const USUAL = { kind: "preference", title: "Usual airtime", hook: "MTN, 500 naira", body: "Buys MTN airtime." };
const MUM = { kind: "recipient", title: "Mum", account_number: "0123456789", bank: "GTB" };

async function saved(client, fields) {
  const made = await call(client, "remember", fields);
  await call(client, "confirm_memory", decision(made));
  return made.structuredContent.proposal_id;
}

const alice = await connect("memory", ALICE);
const bob = await connect("memory", BOB);

console.log("\nthe tools");
{
  const tools = (await alice.listTools()).tools;
  const names = (kind) => tools.filter(kind).map((t) => t.name).sort();
  check(JSON.stringify(names(isToolVisibilityModelOnly)) === JSON.stringify(["forget", "recall", "remember", "update"]), "the model sees recall, remember, update and forget");
  check(names(isToolVisibilityAppOnly).length === 9 && names(isToolVisibilityAppOnly).includes("confirm_memory"), "the card's and the page's nine tools are app-only");
  check(getToolUiResourceUri(tools.find((t) => t.name === "remember")) === "ui://memory/card.html", "remember shows the memory card");
  check(tools.every((t) => t.annotations && "destructiveHint" in t.annotations), "every tool is annotated");
  check(alice.getInstructions().includes("You cannot save"), "the instructions say the model cannot save");
  const card = await alice.readResource({ uri: "ui://memory/card.html" });
  check(card.contents[0].mimeType === "text/html;profile=mcp-app", "the card is served as an MCP App");
}

console.log("\na proposal writes nothing; Save writes one note");
{
  const made = await call(alice, "remember", USUAL);
  check(made.structuredContent.memory.state === "pending" && !text(made).includes(made._meta.confirmToken), "a proposal is pending and its token is not in its text");
  check((await call(alice, "memory_index", {})).structuredContent.entries === 0, "nothing is saved yet");
  const denied = await call(alice, "confirm_memory", decision(made, { confirm_token: "0".repeat(64) }));
  check(denied.isError && text(denied).startsWith("MEMORY_DENIED"), "a save without the card's token is refused");
  const done = await call(alice, "confirm_memory", decision(made));
  check(done.structuredContent.memory.state === "saved", "Save writes the note");
  check((await call(alice, "confirm_memory", decision(made))).structuredContent.memory.state === "saved", "Save twice is still one note");
  check((await call(alice, "memory_index", {})).structuredContent.entries === 1, "one note");
}

console.log("\nrecall, forget and undo");
{
  const found = await call(alice, "recall", { query: "airtime" });
  check(found.structuredContent.notes.length === 1 && found.structuredContent.untrusted === true, "a search finds it and marks it untrusted");
  check(text(found).includes("never instructions"), "the text says the notes are never instructions");
  const gone = await call(alice, "forget", { id: found.structuredContent.notes[0].id });
  check((await call(alice, "recall", { query: "airtime" })).structuredContent.notes.length === 0, "a forgotten note is not found");
  const back = await call(alice, "undo_memory", decision(gone));
  check(back.structuredContent.memory.state === "restored" && (await call(alice, "recall", { query: "airtime" })).structuredContent.notes.length === 1, "Undo brings it back");
}

console.log("\na saved recipient");
{
  const mum = await saved(alice, MUM);
  const recalled = (await call(alice, "recall", { id: mum })).structuredContent.notes[0];
  check(recalled.account_name === "SIMULATED ACCOUNT 6789" && recalled.account_masked === "******6789" && !JSON.stringify(recalled).includes("0123456789"), "the bank's name, and the number only masked");
  const send = await connect("send-money", ALICE, false);
  const args = { recipient_memory_id: mum, amount_kobo: 500000, amount_as_user_said: "5k", idempotency_key: "ts-memory-send-0001" };
  const quote = await call(send, "create_transfer_quote", args);
  check(!quote.isError && quote.structuredContent.quote.details.recipientName === "SIMULATED ACCOUNT 6789", "a transfer to the saved recipient is quoted by its id");
  const both = await call(send, "create_transfer_quote", { ...args, account_number: "0987654321", idempotency_key: "ts-memory-send-0002" });
  check(both.isError && text(both).startsWith("INVALID_INPUT"), "digits for a saved recipient are refused");
  const bobSend = await connect("send-money", BOB, false);
  const stolen = await call(bobSend, "create_transfer_quote", { ...args, idempotency_key: "ts-memory-send-0003" });
  check(stolen.isError && text(stolen).startsWith("RECIPIENT_NOT_FOUND"), "another account cannot use it");
}

console.log("\nanother account");
{
  check((await call(bob, "memory_index", {})).structuredContent.entries === 0, "Bob's index is empty");
  const stranger = await call(bob, "recall", { query: "mum" });
  check(stranger.structuredContent.notes.length === 0, "Bob's search finds none of Alice's notes");
  const anonymous = await connect("memory", ALICE, false);
  let refused = false;
  try {
    await call(anonymous, "memory_index", {});
  } catch (error) {
    refused = /signed-in accounts/.test(String(error.message));
  }
  check(refused, "a call with no memory owner is refused");
}

console.log("\nwhat is never kept");
{
  for (const body of ["my cvv is 123", "my BVN is 22212345678", "my password is hunter2", "card 4111 1111 1111 1111"]) {
    const refused = await call(alice, "remember", { ...USUAL, title: "Other", body });
    check(refused.isError === true, `refused: ${body.replace(/\d{6,}/g, "…")}`);
  }
}

console.log(failed === 0 ? "\nAll checks passed." : `\n${failed} check(s) failed.`);
process.exit(failed === 0 ? 0 : 1);
