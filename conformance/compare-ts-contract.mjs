// SPDX-License-Identifier: AGPL-3.0-or-later
// Compares the Python Worker's connectors with the TypeScript originals: tools/list (names, descriptions, schemas,
// annotations, _meta), instructions, and the QuoteView, receipt and text each returns for the same requests. Prints
// every difference. A manual check: it needs the TypeScript demo built, and runs it from a copy of its dist/ in a
// directory with no .env, so no key of the owner's is ever read:
//   mkdir /tmp/ts-copy && cp -r reference/ts-demo/dist reference/ts-demo/package.json /tmp/ts-copy
//   ln -s "$PWD/reference/ts-demo/node_modules" /tmp/ts-copy/node_modules
//   TSDIR=/tmp/ts-copy PY=http://localhost:8787 node conformance/compare-ts-contract.mjs   (Worker with ENABLE_TEST_ROUTES=1)
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PY = process.env.PY ?? "http://localhost:8882";
const TSDIR = process.env.TSDIR;
const bins = { "paystack-pay": "paystack-pay", "send-money": "send-money", airtime: "airtime", "food-order": "food-order" };
const diffs = [];
const diff = (where, what) => diffs.push(`${where}: ${what}`);

async function tsClient(bin) {
  const ledgerDir = mkdtempSync(join(tmpdir(), "ts-ledger-"));
  const c = new Client({ name: "cmp", version: "0" });
  await c.connect(new StdioClientTransport({
    command: process.execPath, args: [`${TSDIR}/dist/connectors/${bin}/bin.js`], cwd: TSDIR,
    env: { PATH: process.env.PATH, LEDGER_PATH: `${ledgerDir}/ledger.sqlite`, PAYSTACK_MODE: "simulated", VTPASS_MODE: "simulated", ENV_FILE: "/nonexistent", SIM_CHECKOUT_PORT: "8896", PER_PAYMENT_LIMIT_NGN: "50000", DAILY_LIMIT_NGN: "100000" },
  }));
  return c;
}
async function pyClient(name) {
  const c = new Client({ name: "cmp", version: "0" });
  await c.connect(new StreamableHTTPClientTransport(new URL(`${PY}/${name}/mcp`)));
  return c;
}

const strip = (schema) => {
  if (Array.isArray(schema)) return schema.map(strip);
  if (schema && typeof schema === "object") {
    const out = {};
    for (const [k, v] of Object.entries(schema)) {
      if (k === "$schema" || k === "title") continue;
      out[k] = strip(v);
    }
    return out;
  }
  return schema;
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const plain = (text) => text?.replace(/qt-[0-9a-f]{20}/g, "qt-ID");
const sortKeys = (v) => Array.isArray(v) ? v.map(sortKeys) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sortKeys(v[k])])) : v;

function compareSchemas(where, ts, py) {
  const a = sortKeys(strip(ts)), b = sortKeys(strip(py));
  const props = (s) => Object.keys(s.properties ?? {}).sort();
  if (!same(props(a), props(b))) diff(where, `properties differ: TS ${props(a)} vs PY ${props(b)}`);
  if (!same((a.required ?? []).sort(), (b.required ?? []).sort())) diff(where, `required differ: TS ${a.required} vs PY ${b.required}`);
  if (a.additionalProperties !== b.additionalProperties) diff(where, `additionalProperties: TS ${a.additionalProperties} vs PY ${b.additionalProperties}`);
  for (const p of props(a)) {
    const pa = a.properties[p], pb = b.properties[p] ?? {};
    for (const k of new Set([...Object.keys(pa), ...Object.keys(pb)])) {
      if (k === "description") { if (pa[k] !== pb[k]) diff(`${where}.${p}`, `description differs`); continue; }
      if (!same(pa[k], pb[k])) diff(`${where}.${p}`, `${k}: TS ${JSON.stringify(pa[k])} vs PY ${JSON.stringify(pb[k])}`);
    }
  }
}

async function compareTools(name, ts, py) {
  const a = Object.fromEntries((await ts.listTools()).tools.map((t) => [t.name, t]));
  const b = Object.fromEntries((await py.listTools()).tools.map((t) => [t.name, t]));
  if (!same(Object.keys(a).sort(), Object.keys(b).sort())) diff(name, `tool names differ: TS ${Object.keys(a).sort()} vs PY ${Object.keys(b).sort()}`);
  for (const tool of Object.keys(a)) {
    if (!b[tool]) continue;
    const where = `${name}.${tool}`;
    if (a[tool].description !== b[tool].description) diff(where, `description differs`);
    if (a[tool].title !== b[tool].title) diff(where, `title: TS ${a[tool].title} vs PY ${b[tool].title}`);
    if (!same(sortKeys(a[tool].annotations), sortKeys(b[tool].annotations))) diff(where, `annotations: TS ${JSON.stringify(a[tool].annotations)} vs PY ${JSON.stringify(b[tool].annotations)}`);
    if (!same(sortKeys(a[tool]._meta), sortKeys(b[tool]._meta))) diff(where, `_meta: TS ${JSON.stringify(a[tool]._meta)} vs PY ${JSON.stringify(b[tool]._meta)}`);
    compareSchemas(`${where}.inputSchema`, a[tool].inputSchema, b[tool].inputSchema);
  }
  const ra = (await ts.listResources()).resources.map((r) => r.uri).sort(), rb = (await py.listResources()).resources.map((r) => r.uri).sort();
  if (!same(ra, rb)) diff(name, `resources: TS ${ra} vs PY ${rb}`);
  const ia = ts.getInstructions() ?? "", ib = py.getInstructions() ?? "";
  if (ia !== ib) {
    const la = ia.split("\n"), lb = ib.split("\n");
    for (const l of la) if (!lb.includes(l)) diff(name, `instructions: only in TS: ${l.slice(0, 90)}`);
    for (const l of lb) if (!la.includes(l)) diff(name, `instructions: only in PY: ${l.slice(0, 90)}`);
  }
}

// Structure of a value: keys and JS types, recursively.
const shape = (v) => v === null ? "null" : Array.isArray(v) ? [v.length ? shape(v[0]) : "empty"] : typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, shape(v[k])])) : typeof v;
function compareShapes(where, ts, py, path = "") {
  const a = shape(ts), b = shape(py);
  const walk = (x, y, p) => {
    if (typeof x === "object" && x && typeof y === "object" && y && !Array.isArray(x) && !Array.isArray(y)) {
      for (const k of new Set([...Object.keys(x), ...Object.keys(y)])) {
        if (!(k in x)) diff(where, `${p}.${k} only in PY`);
        else if (!(k in y)) diff(where, `${p}.${k} only in TS`);
        else walk(x[k], y[k], `${p}.${k}`);
      }
    } else if (Array.isArray(x) && Array.isArray(y)) walk(x[0], y[0], `${p}[]`);
    else if (x !== y && !(x === "null" || y === "null")) diff(where, `${p}: TS ${JSON.stringify(x)} vs PY ${JSON.stringify(y)}`);
  };
  walk(a, b, path);
}
const quote = (r) => r.structuredContent?.quote;
const pick = (v, keys) => Object.fromEntries(keys.map((k) => [k, v?.[k]]));

async function payTs(url) { const u = new URL(url); await fetch(url); await fetch(`${url}/outcome`, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "outcome=success" }); }
async function payPy(url) { const ref = url.split("/").at(-1); await fetch(url); await fetch(`${PY}/sim/checkout/${ref}/pay`, { method: "POST" }); }

const flows = {
  "paystack-pay": async (c, pay, suffix) => {
    const made = await c.callTool({ name: "create_payment_quote", arguments: { amount_kobo: 250000, amount_as_user_said: "2500", description: "Lunch", merchant: "Demo Kitchen", merchant_ref: "o-1", idempotency_key: `cmp-pay-${suffix}0001` } });
    const id = quote(made).id, token = made._meta.approvalToken;
    const approved = await c.callTool({ name: "approve_quote", arguments: { quote_id: id, approval_token: token, displayed_amount_kobo: 250000 } });
    await pay(quote(approved).checkoutUrl);
    const done = await c.callTool({ name: "verify_quote", arguments: { quote_id: id } });
    const status = await c.callTool({ name: "get_quote_status", arguments: { quote_id: id } });
    return { made, approved, done, status };
  },
  "send-money": async (c, pay, suffix) => {
    const made = await c.callTool({ name: "create_transfer_quote", arguments: { account_number: "0000000000", bank_code: "057", amount_kobo: 2500000, amount_as_user_said: "25k", narration: "Rent", idempotency_key: `cmp-send-${suffix}001` } });
    const id = quote(made).id, token = made._meta.approvalToken;
    const done = await c.callTool({ name: "approve_quote", arguments: { quote_id: id, approval_token: token, displayed_amount_kobo: 2500000 } });
    return { made, done };
  },
  airtime: async (c, pay, suffix) => {
    const made = await c.callTool({ name: "create_airtime_quote", arguments: { network: "mtn", phone: "08011111111", amount_kobo: 50000, amount_as_user_said: "500", idempotency_key: `cmp-air-${suffix}0001` } });
    const id = quote(made).id, token = made._meta.approvalToken;
    const approved = await c.callTool({ name: "approve_quote", arguments: { quote_id: id, approval_token: token, displayed_amount_kobo: 50000, readback_confirmed: true } });
    await pay(quote(approved).checkoutUrl);
    const done = await c.callTool({ name: "verify_quote", arguments: { quote_id: id } });
    const data = await c.callTool({ name: "create_data_quote", arguments: { network: "mtn", phone: "08011111111", plan_code: "mtn-10mb-100", idempotency_key: `cmp-data-${suffix}001` } });
    const plans = await c.callTool({ name: "list_data_plans", arguments: { network: "mtn" } });
    return { made, approved, done, data, plans };
  },
  "food-order": async (c, pay, suffix) => {
    const made = await c.callTool({ name: "create_food_quote", arguments: { items: [{ item_id: "zobo", quantity: 2 }], delivery_area: "Yaba", idempotency_key: `cmp-food-${suffix}0001` } });
    const id = quote(made).id, token = made._meta.approvalToken;
    const approved = await c.callTool({ name: "approve_quote", arguments: { quote_id: id, approval_token: token, displayed_amount_kobo: quote(made).amount.kobo } });
    await pay(quote(approved).checkoutUrl);
    const tracking = await c.callTool({ name: "verify_quote", arguments: { quote_id: id } });
    const search = await c.callTool({ name: "search_menu", arguments: { query: "zobo" } });
    const basket = await c.callTool({ name: "build_basket", arguments: { items: [{ item_id: "zobo", quantity: 1 }] } });
    return { made, approved, tracking, search, basket };
  },
};

await fetch(`${PY}/test/reset`, { method: "POST" });
for (const [name, bin] of Object.entries(bins)) {
  const ts = await tsClient(bin), py = await pyClient(name);
  await compareTools(name, ts, py);
  const suffix = Math.random().toString(36).slice(2, 6);
  const a = await flows[name](ts, payTs, suffix), b = await flows[name](py, payPy, suffix);
  for (const step of Object.keys(a)) {
    const qa = quote(a[step]), qb = quote(b[step]);
    if (qa && qb) {
      compareShapes(`${name}.${step}.quote`, qa, qb);
      for (const k of ["phase", "amount", "description", "merchant", "merchantRef", "poll"]) if (!same(qa[k], qb[k])) diff(`${name}.${step}.quote.${k}`, `TS ${JSON.stringify(qa[k])} vs PY ${JSON.stringify(qb[k])}`);
      if (!same(sortKeys(qa.details), sortKeys(qb.details))) diff(`${name}.${step}.quote.details`, `TS ${JSON.stringify(qa.details)} vs PY ${JSON.stringify(qb.details)}`);
      if (qa.receipt && qb.receipt) {
        if (qa.receipt.title !== qb.receipt.title) diff(`${name}.${step}.receipt.title`, `TS ${qa.receipt.title} vs PY ${qb.receipt.title}`);
        const la = qa.receipt.lines.map((l) => l.label), lb = qb.receipt.lines.map((l) => l.label);
        if (!same(la, lb)) diff(`${name}.${step}.receipt.labels`, `TS ${la} vs PY ${lb}`);
      }
      if (qa.message !== qb.message) diff(`${name}.${step}.quote.message`, `TS ${JSON.stringify(qa.message)} vs PY ${JSON.stringify(qb.message)}`);
    } else if (!qa !== !qb) diff(`${name}.${step}`, "structured quote present in only one");
    if (a[step].isError !== b[step].isError && !(a[step].isError === undefined && b[step].isError === undefined)) diff(`${name}.${step}`, `isError: TS ${a[step].isError} vs PY ${b[step].isError}`);
    if (plain(a[step].content?.[0]?.text) !== plain(b[step].content?.[0]?.text)) diff(`${name}.${step}.text`, `\n      TS ${JSON.stringify(plain(a[step].content?.[0]?.text))}\n      PY ${JSON.stringify(plain(b[step].content?.[0]?.text))}`);
    const ma = Object.keys(a[step]._meta ?? {}).sort(), mb = Object.keys(b[step]._meta ?? {}).sort();
    if (!same(ma, mb)) diff(`${name}.${step}._meta`, `TS ${ma} vs PY ${mb}`);
  }
  await ts.close(); await py.close();
}
console.log(diffs.length ? diffs.join("\n") : "no differences");
process.stdout.write("");
process.exit(0);
