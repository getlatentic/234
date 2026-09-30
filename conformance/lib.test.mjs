// SPDX-License-Identifier: AGPL-3.0-or-later
// The suites' shared helper for the stack's ledger, without a stack.
// usage: node --test conformance/lib.test.mjs
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { freshLedger } from "./lib.mjs";

async function connectors(status) {
  const requests = [];
  const server = createServer((request, response) => {
    requests.push(`${request.method} ${request.url}`);
    response.writeHead(status).end('{"ok": true}');
  });
  await new Promise((listening) => server.listen(0, "127.0.0.1", listening));
  return { url: `http://127.0.0.1:${server.address().port}`, requests, close: () => server.close() };
}

test("a suite starts from an empty ledger: the connectors' reset route is called once", async () => {
  const stack = await connectors(200);
  try {
    await freshLedger(stack.url);
    assert.deepEqual(stack.requests, ["POST /test/reset"]);
  } finally {
    stack.close();
  }
});

test("a stack whose test routes are off stops the suite instead of letting it share the day's limit", async () => {
  const stack = await connectors(404);
  try {
    await assert.rejects(freshLedger(stack.url), /\/test\/reset answered 404/);
  } finally {
    stack.close();
  }
});

const HERE = dirname(fileURLToPath(import.meta.url));
const SPENDS = /Approve|approve_quote|pickAndReview|Review order|create_[a-z_]+_quote|airtime [0-9]|Pay ₦/;
const NOT_A_SUITE = new Set(["menu-chat-lib.mjs"]);
const OWN_STACK = new Set(["chat-probe.mjs"]);

test("every suite that approves payments on the shared stack empties the ledger first", () => {
  const spenders = readdirSync(HERE)
    .filter((name) => name.endsWith(".mjs") && !NOT_A_SUITE.has(name) && !OWN_STACK.has(name))
    .filter((name) => {
      const source = readFileSync(join(HERE, name), "utf8");
      return source.includes('from "./lib.mjs"') && SPENDS.test(source);
    });
  assert.ok(spenders.length >= 8, `the scan found the suites (${spenders})`);
  const unguarded = spenders.filter((name) => !/freshLedger\(\)|\/test\/reset/.test(readFileSync(join(HERE, name), "utf8")));
  assert.deepEqual(unguarded, [], "these spend from the day's limit without starting from an empty ledger");
});
