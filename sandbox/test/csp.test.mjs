// SPDX-License-Identifier: AGPL-3.0-or-later
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { MAX_ENTRIES, buildPolicy, canonical, isSigned, refusal, sanitize } from "../src/csp.js";

const vectors = JSON.parse(readFileSync(new URL("./csp-vectors.json", import.meta.url), "utf8"));

test("every declarable source is accepted", () => {
  for (const [field, entry] of vectors.accepted) assert.equal(refusal(field, entry), null, `${field} ${entry}`);
});

test("every other source is refused with a reason", () => {
  for (const [field, entry] of vectors.refused) assert.equal(typeof refusal(field, entry), "string", `${field} ${JSON.stringify(entry)}`);
});

test("a declaration that is not an object yields nothing", () => {
  for (const bad of [null, undefined, 3, "x", ["https://a.example.com"]]) assert.deepEqual(sanitize(bad).csp, {});
});

test("a field that is not a list is refused, unknown fields are ignored", () => {
  const { csp, refused } = sanitize({ connectDomains: "https://a.example.com", extra: ["https://b.example.com"] });
  assert.deepEqual(csp, {});
  assert.equal(refused.length, 1);
});

test("at most sixteen entries a field, the rest refused and duplicates folded", () => {
  const many = Array.from({ length: 20 }, (_, n) => `https://img${n}.example.com`);
  const { csp, refused } = sanitize({ resourceDomains: [...many, many[0]] });
  assert.equal(csp.resourceDomains.length, MAX_ENTRIES);
  assert.equal(refused.length, 5);
  assert.deepEqual(csp.resourceDomains, many.slice(0, MAX_ENTRIES));
});

test("a malformed entry does not spoil its neighbours", () => {
  const { csp, refused } = sanitize({ resourceDomains: ["https://js.paystack.co", "*", "data:", "https://cdn.example.com"] });
  assert.deepEqual(csp.resourceDomains, ["https://js.paystack.co", "https://cdn.example.com"]);
  assert.deepEqual(refused.map((r) => r.entry), ["*", "data:"]);
});

const directives = (policy) => Object.fromEntries(policy.split("; ").map((d) => [d.split(" ")[0], d.split(" ").slice(1).join(" ")]));

test("with nothing declared the policy is the specification's restrictive default", () => {
  assert.deepEqual(directives(buildPolicy({}, "'self' https://host.example")), {
    "default-src": "'none'",
    "script-src": "'self' 'unsafe-inline'",
    "style-src": "'self' 'unsafe-inline'",
    "connect-src": "'self'",
    "img-src": "'self' data:",
    "font-src": "'self'",
    "media-src": "'self' data:",
    "frame-src": "'none'",
    "object-src": "'none'",
    "base-uri": "'self'",
    "form-action": "'none'",
    "frame-ancestors": "'self' https://host.example",
  });
});

test("each declared list goes to exactly the directives the specification names", () => {
  const policy = directives(
    buildPolicy(
      {
        connectDomains: ["https://api.example.com", "wss://live.example.com"],
        resourceDomains: ["https://js.paystack.co"],
        frameDomains: ["https://checkout.paystack.com"],
        baseUriDomains: ["https://base.example.com"],
      },
      "https://host.example",
    ),
  );
  assert.equal(policy["script-src"], "'self' 'unsafe-inline' https://js.paystack.co");
  assert.equal(policy["style-src"], "'self' 'unsafe-inline' https://js.paystack.co");
  assert.equal(policy["connect-src"], "'self' https://api.example.com wss://live.example.com");
  assert.equal(policy["img-src"], "'self' data: https://js.paystack.co");
  assert.equal(policy["font-src"], "'self' https://js.paystack.co");
  assert.equal(policy["media-src"], "'self' data: https://js.paystack.co");
  assert.equal(policy["frame-src"], "https://checkout.paystack.com");
  assert.equal(policy["base-uri"], "https://base.example.com");
  assert.equal(policy["default-src"], "'none'");
  assert.equal(policy["object-src"], "'none'");
});

const vector = JSON.parse(readFileSync(new URL("./signature-vector.json", import.meta.url), "utf8"));

test("the signed text and its signature are the ones the host computes (the same vector runs in Python)", async () => {
  assert.equal(canonical(vector.host, vector.csp), vector.canonical);
  assert.equal(await isSigned(vector.key, vector.host, vector.csp, vector.signature), true);
  assert.equal(await isSigned(vector.key, vector.host, { ...vector.csp, connectDomains: ["https://x.example.com"] }, vector.signature), false);
  assert.equal(await isSigned("other", vector.host, vector.csp, vector.signature), false);
});
