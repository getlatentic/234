// SPDX-License-Identifier: AGPL-3.0-or-later
import assert from "node:assert/strict";
import { createHash, createHmac } from "node:crypto";
import test from "node:test";
import { canonical } from "../src/csp.js";
import worker from "../src/worker.js";

const HOST = "https://host.example";
const env = { HOST_ORIGINS: `${HOST}, http://localhost:8901`, SIGNING_KEY: "test-signing-key" };
const get = (path, init) => worker.fetch(new Request(`https://sandbox.example${path}`, init), env);
const sign = (csp, host = HOST, key = "test-signing-key") => createHmac("sha256", key).update(canonical(host, csp)).digest("hex");
const viewUrl = (csp, sig = sign(csp)) => `/view?host=${encodeURIComponent(HOST)}&csp=${encodeURIComponent(JSON.stringify(csp))}&sig=${sig}`;
const hash = (text) => `'sha256-${createHash("sha256").update(text).digest("base64")}'`;
const policyOf = (response) => Object.fromEntries(response.headers.get("content-security-policy").split("; ").map((d) => [d.split(" ")[0], d.split(" ").slice(1).join(" ")]));

test("the proxy page names its own script and style by hash, and nothing else may run", async () => {
  const response = await get(`/?host=${encodeURIComponent(HOST)}`);
  assert.equal(response.status, 200);
  const page = await response.text();
  const script = page.match(/<script>([\s\S]*?)<\/script>/)[1];
  const style = page.match(/<style>([\s\S]*?)<\/style>/)[1];
  const policy = policyOf(response);
  assert.equal(policy["script-src"], hash(script));
  assert.equal(policy["style-src"], hash(style));
  assert.equal(policy["default-src"], "'none'");
  assert.equal(policy["frame-src"], "'self'");
  assert.equal(policy["frame-ancestors"], HOST);
  assert.equal(policy["base-uri"], "'none'");
  assert.equal((page.match(/<script/g) ?? []).length, 1);
  assert.doesNotMatch(page.replace(script, ""), /src=|href=|<link|<img|<iframe|\son[a-z]+=/i);
});

test("the proxy page is static and safe to hold: no store, no sniffing, no referrer, no cookie", async () => {
  const response = await get(`/?host=${encodeURIComponent(HOST)}`);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(response.headers.get("referrer-policy"), "no-referrer");
  assert.equal(response.headers.get("set-cookie"), null);
  assert.match(response.headers.get("content-type"), /^text\/html/);
  const page = await response.text();
  assert.match(page, /<meta name="host-origin" content="https:\/\/host\.example">/);
});

test("the proxy script holds no state and reaches no network", async () => {
  const page = await (await get(`/?host=${encodeURIComponent(HOST)}`)).text();
  for (const banned of ["fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "indexedDB", "document.cookie", "WebSocket", "eval(", "importScripts"]) {
    assert.ok(!page.includes(banned), banned);
  }
});

test("it answers only for an origin it was configured for", async () => {
  for (const asked of ["https://evil.example", "https://host.example.evil.com", "*", "", "http://host.example"]) {
    assert.equal((await get(`/?host=${encodeURIComponent(asked)}`)).status, 403, asked);
    assert.equal((await get(`/view?host=${encodeURIComponent(asked)}&sig=${sign({}, asked)}`)).status, 403, asked);
  }
  assert.equal((await get("/")).status, 403);
  assert.equal((await get(`/?host=${encodeURIComponent("http://localhost:8901")}`)).status, 200);
  assert.equal(policyOf(await get(`/?host=${encodeURIComponent("http://localhost:8901")}`))["frame-ancestors"], "http://localhost:8901");
});

test("a view's document gets its policy from the declaration, in a header", async () => {
  const csp = { resourceDomains: ["https://js.paystack.co"], frameDomains: ["https://checkout.paystack.com"], connectDomains: ["wss://x.example.com"] };
  const response = await get(viewUrl(csp));
  assert.equal(response.status, 200);
  const policy = policyOf(response);
  assert.equal(policy["script-src"], "'self' 'unsafe-inline' https://js.paystack.co");
  assert.equal(policy["frame-src"], "https://checkout.paystack.com");
  assert.equal(policy["connect-src"], "'self' wss://x.example.com");
  assert.equal(policy["frame-ancestors"], `'self' ${HOST}`);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal((await response.text()).includes("<iframe"), false);
});

test("a policy the host did not sign is not served: a view cannot ask for a wider one", async () => {
  const narrow = { resourceDomains: ["https://js.paystack.co"] };
  const wide = { connectDomains: ["https://evil.example.com"], resourceDomains: ["https://js.paystack.co"] };
  const lines = [];
  const original = console.log;
  console.log = (line) => lines.push(line);
  try {
    for (const url of [
      viewUrl(wide, sign(narrow)),
      viewUrl(narrow, sign(narrow, "https://other.example")),
      viewUrl(narrow, sign(narrow, HOST, "another-key")),
      viewUrl(narrow, "0".repeat(64)),
      viewUrl(narrow, "nothex"),
      `/view?host=${encodeURIComponent(HOST)}&csp=${encodeURIComponent(JSON.stringify(narrow))}`,
      `/view?host=${encodeURIComponent(HOST)}&sig=${sign({})}&csp=${encodeURIComponent(JSON.stringify(wide))}`,
    ]) assert.equal((await get(url)).status, 403, url);
    assert.equal((await get(viewUrl({}))).status, 200, "the empty declaration is signed too");
  } finally {
    console.log = original;
  }
  assert.equal(lines.filter((line) => line.includes("view.unsigned")).length, 7);
});

test("a sandbox with no key serves no view", async () => {
  const response = await worker.fetch(new Request(`https://sandbox.example${viewUrl({})}`), { HOST_ORIGINS: HOST });
  assert.equal(response.status, 503);
});

test("a declaration the worker cannot trust is narrowed even when it is signed", async () => {
  const lines = [];
  const original = console.log;
  console.log = (line) => lines.push(line);
  try {
    const csp = { resourceDomains: ["*", "data:", "https://ok.example.com; script-src *"], connectDomains: ["http://x.example.com"] };
    const policy = policyOf(await get(viewUrl(csp, sign({}))));
    assert.equal(policy["script-src"], "'self' 'unsafe-inline'");
    assert.equal(policy["connect-src"], "'self'");
  } finally {
    console.log = original;
  }
  assert.equal(lines.filter((l) => l.includes("csp.refused")).length, 4);
});

test("the rest is refused: other paths, other methods, other files", async () => {
  assert.equal((await get("/health")).status, 200);
  assert.equal((await get("/proxy.js")).status, 404);
  assert.equal((await get("/../etc/passwd")).status, 404);
  assert.equal((await get(`/?host=${encodeURIComponent(HOST)}`, { method: "POST", body: "x" })).status, 405);
  const head = await get(`/?host=${encodeURIComponent(HOST)}`, { method: "HEAD" });
  assert.equal(head.status, 200);
});

test("with a custom domain the sandbox serves the host's two origins, each framed by itself alone, and the signature binds one", async () => {
  const custom = "https://234.example.com";
  const workersDev = "https://chat.acct.workers.dev";
  const both = { HOST_ORIGINS: `${workersDev},${custom}`, SIGNING_KEY: "test-signing-key" };
  const ask = (path) => worker.fetch(new Request(`https://sandbox.example${path}`), both);
  for (const origin of [custom, workersDev]) {
    const response = await ask(`/?host=${encodeURIComponent(origin)}`);
    assert.equal(response.status, 200, origin);
    assert.equal(policyOf(response)["frame-ancestors"], origin);
  }
  for (const stranger of ["https://example.com", "https://evil.234.example.com", "http://234.example.com", `${custom}.evil.example`]) {
    assert.equal((await ask(`/?host=${encodeURIComponent(stranger)}`)).status, 403, stranger);
  }
  const forWorkersDev = sign({}, workersDev);
  assert.equal((await ask(`/view?host=${encodeURIComponent(workersDev)}&csp=%7B%7D&sig=${forWorkersDev}`)).status, 200);
  assert.equal((await ask(`/view?host=${encodeURIComponent(custom)}&csp=%7B%7D&sig=${forWorkersDev}`)).status, 403);
  assert.equal((await ask(`/view?host=${encodeURIComponent(custom)}&csp=%7B%7D&sig=${sign({}, custom)}`)).status, 200);
});
