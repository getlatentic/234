// SPDX-License-Identifier: AGPL-3.0-or-later
import assert from "node:assert/strict";
import { test } from "node:test";
import { runReady } from "./run.mjs";
import { verdict } from "./report.mjs";
import { GOOD_TOOLS, fakeServer, tool } from "./test/fake-server.mjs";

async function against(options, run = {}) {
  const server = await fakeServer(options);
  try {
    return await runReady({ url: server.url, ...run });
  } finally {
    server.close();
  }
}
const failing = (results) => results.filter((r) => !r.ok && r.level === "must").map((r) => r.id);
const warning = (results) => results.filter((r) => !r.ok && r.level === "should").map((r) => r.id);

test("a server that follows the rules passes", async () => {
  const results = await against({ tools: GOOD_TOOLS });
  assert.deepEqual(failing(results), []);
  assert.equal(verdict(results).failed, 0);
});

test("a payment tool without an idempotency key fails", async () => {
  const bad = GOOD_TOOLS.map((t) => (t.name === "create_payment_quote" ? tool("create_payment_quote", { amount_kobo: { type: "number" } }) : t));
  assert.deepEqual(failing(await against({ tools: bad })), ["money.idempotency-key"]);
});

test("a model-visible approval tool without proof fails", async () => {
  const bad = GOOD_TOOLS.map((t) => (t.name === "approve_quote" ? tool("approve_quote", { quote_id: { type: "string" } }) : t));
  assert.deepEqual(failing(await against({ tools: bad })), ["money.model-cannot-approve"]);
});

test("an approval tool that asks for the person's token is accepted", async () => {
  const ok = GOOD_TOOLS.map((t) => (t.name === "approve_quote" ? { ...t, _meta: undefined } : t));
  assert.deepEqual(failing(await against({ tools: ok })), []);
});

test("missing annotations and thin descriptions fail", async () => {
  const bad = [{ name: "doit", description: "does it", inputSchema: { type: "object", properties: {} } }];
  const failed = failing(await against({ tools: bad }));
  for (const id of ["tools.descriptions", "tools.read-only-hint", "tools.write-hints"]) assert.ok(failed.includes(id), id);
});

test("a server open without sign-in only warns", async () => {
  assert.deepEqual(warning(await against({ tools: GOOD_TOOLS })), ["auth.challenge"]);
});

test("a server that challenges for sign-in passes the auth rules", async () => {
  const results = await against({ tools: GOOD_TOOLS, requireSignIn: true }, { headers: { authorization: "Bearer t" } });
  assert.ok(results.filter((r) => r.id.startsWith("auth.")).every((r) => r.ok), JSON.stringify(results.filter((r) => r.id.startsWith("auth."))));
});

test("replaying a sample call with the same key gives the same result", async () => {
  const calls = [{ tool: "create_payment_quote", args: { amount_kobo: 100, idempotency_key: "k-0000001" } }];
  const results = await against({ tools: GOOD_TOOLS }, { calls });
  assert.ok(results.find((r) => r.id === "replay.create_payment_quote").ok);
});

test("a repeated key that creates a second result fails", async () => {
  const calls = [{ tool: "create_payment_quote", args: { amount_kobo: 100, idempotency_key: "k-0000001" } }];
  assert.deepEqual(failing(await against({ tools: GOOD_TOOLS, repeatsResult: false }, { calls })), ["replay.create_payment_quote"]);
});
