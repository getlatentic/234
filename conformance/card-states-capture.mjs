// SPDX-License-Identifier: AGPL-3.0-or-later
// Records real QuoteViews for the card-state screenshots: it drives the connectors of running local
// Workers (all simulators, no network beyond localhost) and writes conformance/card-states.fixtures.json.
// Each fixture is the tool result a host hands the card: { structuredContent: { quote }, _meta: { approvalToken } }.
//
// usage: node conformance/card-states-capture.mjs
//   PLAIN  Worker with FOOD_STEP_SECONDS small                      (default http://localhost:8890)
//   OTP    Worker started with --var SIM_TRANSFER_OTP:1             (default http://localhost:8891)
//   NOPAY  Worker started with --var SIM_PAYOUTS_REFUSED:1          (default http://localhost:8892)
import { writeFile } from "node:fs/promises";

const PLAIN = process.env.PLAIN ?? "http://localhost:8890";
const OTP = process.env.OTP ?? "http://localhost:8891";
const NOPAY = process.env.NOPAY ?? "http://localhost:8892";
const run = Math.random().toString(36).slice(2, 8);
let rpcId = 0;
let keySeq = 0;
const key = (tag) => `states-${run}-${tag}-${String(++keySeq).padStart(3, "0")}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const call = async (base, connector, name, args) => {
  const body = { jsonrpc: "2.0", id: ++rpcId, method: "tools/call", params: { name, arguments: args } };
  const res = await fetch(`${base}/${connector}/mcp`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(body),
  });
  return (await res.json()).result;
};

const quoteOf = (result) => result.structuredContent.quote;
const approveArgs = (made, extra = {}) => ({
  quote_id: quoteOf(made).id,
  approval_token: made._meta.approvalToken,
  displayed_amount_kobo: quoteOf(made).amount.kobo,
  ...extra,
});
const pay = (base, quote, outcome = "pay") => fetch(`${quote.checkoutUrl.replace(/^https?:\/\/[^/]+/, base)}/${outcome}`, { method: "POST" });

const fixtures = {};
// A fixture keeps the token of the result it came from, as the host passes it to the card.
const keep = (name, result, token) => {
  const quote = quoteOf(result);
  fixtures[name] = { structuredContent: { quote }, _meta: { approvalToken: token ?? result._meta?.approvalToken ?? "token-not-held" } };
};

async function transfers() {
  const args = (over = {}) => ({
    account_number: "0000000000", bank_code: "057", amount_kobo: 2_500_000, amount_as_user_said: "25k",
    narration: "Rent share", idempotency_key: key("transfer"), ...over,
  });
  const made = await call(PLAIN, "send-money", "create_transfer_quote", args());
  keep("transfer/approve", made);
  keep("transfer/succeeded", await call(PLAIN, "send-money", "approve_quote", approveArgs(made)), made._meta.approvalToken);
  const declined = await call(PLAIN, "send-money", "create_transfer_quote", args());
  keep("transfer/declined", await call(PLAIN, "send-money", "decline_quote", { quote_id: quoteOf(declined).id, approval_token: declined._meta.approvalToken }), declined._meta.approvalToken);

  const otpMade = await call(OTP, "send-money", "create_transfer_quote", args());
  keep("transfer/otp", await call(OTP, "send-money", "approve_quote", approveArgs(otpMade)), otpMade._meta.approvalToken);
  const wrong = await call(OTP, "send-money", "submit_otp", { quote_id: quoteOf(otpMade).id, otp: "000000" });
  fixtures["transfer/otp-rejected"] = { ...fixtures["transfer/otp"], notice: wrong.content[0].text };

  const refused = await call(NOPAY, "send-money", "create_transfer_quote", args());
  keep("transfer/unavailable", await call(NOPAY, "send-money", "approve_quote", approveArgs(refused)), refused._meta.approvalToken);
}

async function airtime() {
  const airtimeArgs = (phone) => ({
    network: "mtn", phone, amount_kobo: 50_000, amount_as_user_said: "₦500", idempotency_key: key("airtime"),
  });
  const paid = async (phone, settle) => {
    const made = await call(PLAIN, "airtime", "create_airtime_quote", airtimeArgs(phone));
    const approved = await call(PLAIN, "airtime", "approve_quote", approveArgs(made, { readback_confirmed: true }));
    await pay(PLAIN, quoteOf(approved));
    return { made, approved, view: await settle(quoteOf(made).id) };
  };
  const verify = (id) => call(PLAIN, "airtime", "verify_quote", { quote_id: id });

  const first = await call(PLAIN, "airtime", "create_airtime_quote", airtimeArgs("08011111111"));
  keep("airtime/approve", first);
  keep("airtime/checkout", await call(PLAIN, "airtime", "approve_quote", approveArgs(first, { readback_confirmed: true })), first._meta.approvalToken);

  const ok = await paid("08011111111", verify);
  keep("airtime/succeeded", ok.view, ok.made._meta.approvalToken);
  const failed = await paid("100000000000", verify);
  keep("airtime/attention", failed.view, failed.made._meta.approvalToken);
  const pending = await paid("201000000000", verify);
  keep("airtime/processing", pending.view, pending.made._meta.approvalToken);

  const plans = (await call(PLAIN, "airtime", "list_data_plans", { network: "mtn" })).structuredContent.plans;
  const plan = plans.find((p) => p.code === "mtn-100mb-1000") ?? plans.at(-1);
  const data = await call(PLAIN, "airtime", "create_data_quote", {
    network: "mtn", phone: "08011111111", plan_code: plan.code, idempotency_key: key("data"),
  });
  keep("data/approve", data);
  const dataApproved = await call(PLAIN, "airtime", "approve_quote", approveArgs(data, { readback_confirmed: true }));
  await pay(PLAIN, quoteOf(dataApproved));
  keep("data/succeeded", await verify(quoteOf(data).id), data._meta.approvalToken);
}

async function food() {
  const items = [{ item_id: "beef-suya", quantity: 1 }, { item_id: "chapman", quantity: 2 }];
  const made = await call(PLAIN, "food-order", "create_food_quote", { items, delivery_area: "Surulere", idempotency_key: key("food") });
  keep("food/approve", made);
  const approved = await call(PLAIN, "food-order", "approve_quote", approveArgs(made));
  keep("food/checkout", approved, made._meta.approvalToken);
  await pay(PLAIN, quoteOf(approved));
  const seen = new Set();
  for (let waited = 0; waited < 40_000 && !seen.has("done"); waited += 500) {
    const view = await call(PLAIN, "food-order", "verify_quote", { quote_id: quoteOf(made).id });
    const q = quoteOf(view);
    const name = q.tracking ? `food/track-${q.tracking.current}` : q.phase === "succeeded" ? "food/succeeded" : null;
    if (name && !seen.has(name)) {
      seen.add(name);
      keep(name, view, made._meta.approvalToken);
    }
    if (q.phase === "succeeded") seen.add("done");
    await sleep(500);
  }
  const big = await call(PLAIN, "food-order", "create_food_quote", {
    items: [["jollof-chicken", 1], ["fried-rice-dodo", 1], ["egusi-pounded-yam", 1], ["beef-suya", 2], ["chapman", 2], ["zobo", 3]].map(([item_id, quantity]) => ({ item_id, quantity })),
    delivery_area: "Victoria Island", idempotency_key: key("food-big"),
  });
  if (big.isError) console.log("big basket refused:", big.content?.[0]?.text);
  else {
    keep("food/approve-many", big);
    const bigApproved = await call(PLAIN, "food-order", "approve_quote", approveArgs(big));
    await pay(PLAIN, quoteOf(bigApproved));
    for (let waited = 0; waited < 40_000; waited += 500) {
      const view = await call(PLAIN, "food-order", "verify_quote", { quote_id: quoteOf(big).id });
      if (quoteOf(view).phase === "succeeded") { keep("food/succeeded-many", view, big._meta.approvalToken); break; }
      await sleep(500);
    }
  }
}

await transfers();
await airtime();
await food();
const names = Object.keys(fixtures).sort();
await writeFile(new URL("card-states.fixtures.json", import.meta.url), `${JSON.stringify(fixtures, null, 1)}\n`);
console.log(`${names.length} states:\n  ${names.join("\n  ")}`);
