// SPDX-License-Identifier: AGPL-3.0-or-later
// The QuoteViews recorded by card-states-capture.mjs (card-states.fixtures.json), and the states that need a
// hostile input (a long name) or a clock (a transfer in flight), derived from them.
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));

export const fixtures = JSON.parse(await readFile(`${here}card-states.fixtures.json`, "utf8"));
export const copy = (name) => structuredClone(fixtures[name]);
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
  q.wallet = { covers: true };
});
fixtures["airtime/failed"] = derive("airtime/checkout", (q) => {
  Object.assign(q, { phase: "failed", checkoutUrl: null, message: "Payment failed. Nothing was charged." });
});

// Recorded quotes are long expired; a card shows a live quote until a minute before it lapses.
const EXPIRES_IN = { "transfer/expiring": 45_000 };
export const refreshed = (key, view) => {
  const quote = { ...view.structuredContent.quote, expiresAt: new Date(Date.now() + (EXPIRES_IN[key] ?? 300_000)).toISOString() };
  return { ...view, structuredContent: { quote } };
};

const CONNECTOR_OF = { transfer: "transfer", airtime: "airtime", data: "airtime", food: "food" };
export const nameOf = (key) => {
  const [group, ...rest] = key.split("/");
  return `${CONNECTOR_OF[group] ?? group}-${group === "data" ? "data-" : ""}${rest.join("-")}`;
};
