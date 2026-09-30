// SPDX-License-Identifier: AGPL-3.0-or-later
// A stand-in for Paystack's API on this machine, so the connectors can run in Paystack test mode without a key or a
// network, and so a real Paystack test transaction can be reached without the key ever leaving this process.
//
//   node conformance/paystack-rig.mjs PORT                fake: answers initialize and verify itself
//   PAYSTACK_RIG=real node conformance/paystack-rig.mjs PORT   forwards both to api.paystack.co with the test key from
//                                                          .env.local at the repository root; it refuses any key
//                                                          that does not start sk_test_, and prints no key, no code
//                                                          and no authorization link.
// The connectors are started with PAYSTACK_API_URL=http://127.0.0.1:PORT and a dummy sk_test_ key, which is all
// they hold. Test controls: POST /rig/pay {reference} makes a transaction paid in the fake; GET /rig/state lists them.
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { randomBytes } from "node:crypto";

const port = Number(process.argv[2] ?? 8926);
const real = process.env.PAYSTACK_RIG === "real";

function testKey() {
  const line = readFileSync(new URL("../.env.local", import.meta.url), "utf8")
    .split("\n")
    .find((l) => l.startsWith("PAYSTACK_TEST_SECRET_KEY="));
  const key = line?.slice("PAYSTACK_TEST_SECRET_KEY=".length).trim().replace(/^["']|["']$/g, "");
  if (!key?.startsWith("sk_test_")) {
    console.error("paystack-rig: refusing to run: there is no sk_test_ key to forward with");
    process.exit(1);
  }
  return key;
}
const key = real ? testKey() : null;

const transactions = new Map();
const json = (res, status, body) => res.writeHead(status, { "content-type": "application/json" }).end(JSON.stringify(body));
const readBody = async (req) => {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {};
};

async function forward(req, res, path, body) {
  const answer = await fetch(`https://api.paystack.co${path}`, {
    method: req.method,
    headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: req.method === "POST" ? JSON.stringify(body) : undefined,
  });
  json(res, answer.status, await answer.json());
}

const routes = {
  "POST /transaction/initialize": async (req, res, _, body) => {
    if (real) return forward(req, res, "/transaction/initialize", body);
    const code = `rig${randomBytes(6).toString("hex")}`;
    transactions.set(body.reference, { code, amount: Number(body.amount), paid: false });
    return json(res, 200, {
      status: true,
      message: "Authorization URL created",
      data: { authorization_url: `https://checkout.paystack.com/${code}`, access_code: code, reference: body.reference },
    });
  },
  "GET /transaction/verify": async (req, res, path) => {
    const reference = decodeURIComponent(path.split("/").pop());
    if (real) return forward(req, res, `/transaction/verify/${encodeURIComponent(reference)}`);
    const found = transactions.get(reference);
    if (!found) return json(res, 404, { status: false, message: "Transaction reference not found" });
    return json(res, 200, {
      status: true,
      message: "Verification successful",
      data: { status: found.paid ? "success" : "abandoned", reference, amount: found.amount, currency: "NGN", gateway_response: found.paid ? "Successful" : "The transaction was not completed", paid_at: found.paid ? new Date().toISOString() : null },
    });
  },
  "POST /rig/pay": async (_req, res, _path, body) => {
    const found = transactions.get(body.reference);
    if (!found) return json(res, 404, { error: "unknown reference" });
    found.paid = true;
    return json(res, 200, { paid: true });
  },
  "GET /rig/state": async (_req, res) => json(res, 200, [...transactions].map(([reference, t]) => ({ reference, paid: t.paid, amount: t.amount }))),
};

createServer(async (req, res) => {
  const path = new URL(req.url, "http://x").pathname;
  const route = routes[`${req.method} ${path}`] ?? routes[`${req.method} ${path.split("/").slice(0, 3).join("/")}`];
  if (!route) return json(res, 404, { status: false, message: "not found" });
  try {
    await route(req, res, path, req.method === "POST" ? await readBody(req) : {});
  } catch (error) {
    json(res, 500, { status: false, message: String(error.message).slice(0, 120) });
  }
}).listen(port, "127.0.0.1", () => console.log(`paystack rig (${real ? "forwarding to Paystack test mode" : "fake"}) on http://127.0.0.1:${port}`));
