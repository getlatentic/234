// SPDX-License-Identifier: AGPL-3.0-or-later
// The sandbox proxy against the specification (ext-apps 2026-01-26, "Sandbox proxy", "Security Implications"), in a real
// browser, with the real sandbox Worker of the stack. A page at the host's origin (served by the browser context at
// /__harness, so the Worker sees a real embedder) speaks the raw protocol to it and reports what it sees:
//   - a different origin and site than the host, no cookie or storage of the host reachable, nothing sent to the proxy
//     but its own requests
//   - proxy-ready, then the raw HTML in sandbox-resource-ready, loaded under the CSP built from the declaration
//   - every directive: what is declared loads, what is not is blocked and reported as a violation
//   - messages forwarded both ways unless they are `ui/notifications/sandbox-*`, and nothing the proxy invents
//   - permissions to the frame's `allow`, sandbox flags narrowed to the ones that are safe
// usage: PORT_BASE=8920 node conformance/sandbox-proxy.mjs   (a stack without ALT_RUNNERS; ENGINE=webkit for Safari's engine)
import { createHmac } from "node:crypto";
import { createServer } from "node:http";
import { chromium, webkit } from "playwright";
import { pause, suite } from "./lib.mjs";

const engine = process.env.ENGINE === "webkit" ? webkit : chromium;
const BASE = Number(process.env.PORT_BASE ?? 8900);
const SANDBOX = `http://127.0.0.1:${BASE + 5}`;
// The page that speaks to the proxy must be at an origin the sandbox serves: the stack lists the hosts of its
// alternative turn runners (base+3, base+4), which a stack without ALT_RUNNERS leaves free.
const HOST = `http://localhost:${BASE + 3}`;
const INTRUDER = `http://localhost:${BASE + 7}`;
// The host signs the policy of every view with the key it shares with the sandbox (the stack's dummy one).
const KEY = process.env.SANDBOX_SIGNING_KEY ?? "dummy-local-sandbox-signing-key";
const FIELDS = ["connectDomains", "resourceDomains", "frameDomains", "baseUriDomains"];
const sign = (csp = {}) =>
  createHmac("sha256", KEY).update([HOST, ...FIELDS.filter((f) => csp[f]?.length).map((f) => `${f}=${csp[f].join(",")}`)].join("\n")).digest("hex");
const { check, finish } = suite(`Sandbox proxy (${process.env.ENGINE ?? "chromium"})`);
const browser = await engine.launch();

const HARNESS = `<!doctype html><meta charset=utf-8><title>harness</title><body>
<script>
window.wire = [];
window.frames_ = [];
addEventListener("message", (event) => {
  const frame = frames_.find((f) => f.contentWindow === event.source);
  window.wire.push({ from: frame?.id ?? "?", origin: event.origin, data: event.data });
});
window.embed = (id, { host = location.origin, sandbox = "allow-scripts allow-same-origin", allow } = {}) => {
  const f = document.createElement("iframe");
  f.id = id; f.setAttribute("sandbox", sandbox); if (allow) f.setAttribute("allow", allow);
  f.src = ${JSON.stringify(SANDBOX)} + "/?host=" + encodeURIComponent(host);
  document.body.append(f); frames_.push(f); return f;
};
window.send = (id, message) => frames_.find((f) => f.id === id).contentWindow.postMessage(message, ${JSON.stringify(SANDBOX)});
</script>`;

const rpc = (method, params, id) => ({ jsonrpc: "2.0", method, params, ...(id === undefined ? {} : { id }) });
const READY = "ui/notifications/sandbox-proxy-ready";
const RESOURCE = "ui/notifications/sandbox-resource-ready";

// A view that reports what it can do and what it is told; it is written into the proxy as raw HTML.
const VIEW = (extra = "") => `<!doctype html><html><head><meta charset=utf-8></head><body><script>
const out = { violations: [], loaded: [] };
document.addEventListener("securitypolicyviolation", (e) => out.violations.push(e.effectiveDirective + " " + e.blockedURI.replace(/[?#].*/, "")));
const tell = (method, params) => parent.postMessage({ jsonrpc: "2.0", method, params }, "*");
addEventListener("message", (e) => { if (e.source === parent) tell("test/echo", e.data); });
${extra}
setTimeout(() => tell("test/report", out), 1500);
<\/script></body></html>`;

const serve = (port, body) =>
  new Promise((resolve, reject) => {
    const server = createServer((_req, res) => res.writeHead(200, { "content-type": "text/html" }).end(body));
    server.once("error", reject);
    server.listen(port, "localhost", () => resolve(server));
  });
const servers = [await serve(BASE + 3, HARNESS), await serve(BASE + 7, `<!doctype html><iframe id=x src="${SANDBOX}/?host=${encodeURIComponent(HOST)}"></iframe>`)];

async function newPage() {
  const context = await browser.newContext({ viewport: { width: 500, height: 700 } });
  const page = await context.newPage();
  await page.goto(`${HOST}/`);
  return { context, page };
}
const wire = (page) => page.evaluate(() => window.wire);
const waitFor = async (page, test, ms = 8000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const found = (await wire(page)).find(test);
    if (found) return found;
    await pause(50);
  }
  return null;
};

console.log("the proxy");
let { context, page } = await newPage();
await page.evaluate(() => embed("a"));
const ready = await waitFor(page, (m) => m.data?.method === READY);
check(Boolean(ready) && ready.origin === SANDBOX, `sends ${READY} from the sandbox origin (${ready?.origin})`);
check(new URL(SANDBOX).origin !== new URL(HOST).origin && new URL(SANDBOX).hostname !== new URL(HOST).hostname, `the host (${new URL(HOST).host}) and the sandbox (${new URL(SANDBOX).host}) are different origins on different hostnames`);
const proxy = page.frames().find((f) => f.url().startsWith(`${SANDBOX}/?`));
check((await proxy.evaluate(() => { try { void window.top.document; return "reachable"; } catch { return "blocked"; } })) === "blocked", "the proxy cannot reach the host page's document");

console.log("cookies and storage");
await page.evaluate(() => { document.cookie = "host_cookie=1; path=/"; localStorage.setItem("host_key", "1"); });
const seen = await proxy.evaluate(() => ({ cookie: document.cookie, ls: localStorage.getItem("host_key"), n: localStorage.length }));
check(seen.cookie === "" && seen.ls === null, `the host's cookie and localStorage are not readable in the proxy (cookie "${seen.cookie}", storage ${seen.ls})`);
const headers = [];
page.on("request", async (r) => { if (r.url().startsWith(SANDBOX)) headers.push(await r.allHeaders()); });
await page.evaluate(() => embed("b"));
await waitFor(page, (m) => m.from === "b" && m.data?.method === READY);
await pause(300);
check(headers.length > 0 && headers.every((h) => !("cookie" in h)), `no request to the sandbox carried a cookie (${headers.length} requests)`);
check((await page.evaluate(() => document.cookie)).includes("host_cookie=1"), "while the host page still holds its own cookie");

console.log("loading a view: the policy comes from the declaration");
await context.route("https://declared.example.com/**", (route) => route.fulfill({ contentType: "text/javascript", headers: { "access-control-allow-origin": "*" }, body: "window.__declared = 'ran'; parent.postMessage({jsonrpc:'2.0',method:'test/declared'}, '*');" }));
await context.route("https://undeclared.example.com/**", (route) => route.fulfill({ contentType: "text/javascript", body: "parent.postMessage({jsonrpc:'2.0',method:'test/undeclared'}, '*');" }));
const probes = `
  const add = (tag, attrs) => { const n = document.createElement(tag); Object.assign(n, attrs); document.body.append(n); return n; };
  add("script", { src: "https://declared.example.com/ok.js" });
  add("script", { src: "https://undeclared.example.com/x.js" });
  add("img", { src: "https://undeclared.example.com/x.png" });
  add("img", { src: "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", onload: () => out.loaded.push("data-img") });
  add("iframe", { src: "https://undeclared.example.com/frame" });
  add("object", { data: "https://declared.example.com/o" });
  fetch("https://undeclared.example.com/api").then(() => out.loaded.push("fetch-undeclared"), () => undefined);
  try { new WebSocket("wss://undeclared.example.com/socket"); } catch (e) { out.ws = "threw"; }
  try { eval("1+1"); out.loaded.push("eval"); } catch { out.evalBlocked = true; }
  const base = document.createElement("base"); base.href = "https://undeclared.example.com/"; document.head.append(base);
  out.inline = "ran";
  document.body.insertAdjacentHTML("beforeend", '<div id=x></div>');
  const stamp = document.createElement("div"); stamp.setAttribute("style", "color:red"); document.body.append(stamp); out.style = "ok";
`;
await page.evaluate(([id, html, csp, signature]) => { window.send(id, { jsonrpc: "2.0", method: "ui/notifications/sandbox-resource-ready", params: { html, csp, signature } }); }, ["a", VIEW(probes), { resourceDomains: ["https://declared.example.com"] }, sign({ resourceDomains: ["https://declared.example.com"] })]);
const report = await waitFor(page, (m) => m.data?.method === "test/report");
const out = report?.data?.params ?? { violations: [], loaded: [] };
const blockedBy = (directive, url) => out.violations.some((v) => v.startsWith(directive) && v.includes(url));
check(Boolean(report), "the view loaded and reported (its inline script ran under 'unsafe-inline')");
check((await wire(page)).some((m) => m.data?.method === "test/declared"), "a script from a declared resource domain ran");
check(!(await wire(page)).some((m) => m.data?.method === "test/undeclared") && blockedBy("script-src", "https://undeclared.example.com/x.js"), "a script from an undeclared origin was blocked, and reported as a violation");
check(blockedBy("img-src", "https://undeclared.example.com/x.png"), "an image from an undeclared origin was blocked");
check(out.loaded.includes("data-img"), "an image from data: loads (img-src has data:)");
check(blockedBy("frame-src", "https://undeclared.example.com"), "a nested frame is blocked with none declared (frame-src 'none')");
check(blockedBy("object-src", "https://declared.example.com"), "an object is blocked even from a declared origin (object-src 'none')");
check(out.violations.some((v) => v.startsWith("connect-src") && v.includes("undeclared.example.com/api")) && !out.loaded.includes("fetch-undeclared"), "a request to an undeclared origin is blocked (connect-src)");
check(out.violations.some((v) => v.startsWith("connect-src") && v.includes("wss://undeclared.example.com")), "and so is a WebSocket");
check(out.evalBlocked === true && (process.env.ENGINE === "webkit" || out.violations.some((v) => v.startsWith("script-src") && v.includes("eval"))), "eval is blocked (no 'unsafe-eval')");
check(out.violations.some((v) => v.startsWith("base-uri")), "a <base> to another origin is blocked (base-uri 'self')");
check(out.inline === "ran" && out.style === "ok", "inline script and inline style run ('unsafe-inline' is in the specification's policy)");
const view = page.frames().find((f) => new URL(f.url()).pathname === "/view");
const frameElement = await view.frameElement();
check((await frameElement.getAttribute("sandbox")) === "allow-scripts", 'the view is sandboxed with allow-scripts and nothing else (no allow-same-origin, forms, popups or navigation)');
check((await frameElement.getAttribute("allow")) === null, "with no permission granted the frame has no allow attribute");
check((await view.evaluate(() => { try { return document.cookie, "readable"; } catch { return "blocked"; } })) === "blocked", "the view has no origin of its own: document.cookie is refused to it");
const policy = (await context.request.get(view.url())).headers()["content-security-policy"];
check(policy === "default-src 'none'; script-src 'self' 'unsafe-inline' https://declared.example.com; style-src 'self' 'unsafe-inline' https://declared.example.com; connect-src 'self'; img-src 'self' data: https://declared.example.com; font-src 'self' https://declared.example.com; media-src 'self' data: https://declared.example.com; frame-src 'none'; object-src 'none'; base-uri 'self'; form-action 'none'; frame-ancestors 'self' " + HOST, `the served policy is the specification's, exactly (${policy?.slice(0, 60)}...)`);
check((await page.evaluate(() => window.wire.filter((m) => m.data?.method === "ui/notifications/sandbox-resource-ready").length)) === 0, "the proxy never sent the host a sandbox-resource-ready of its own");

console.log("messages, both ways");
const base = (await wire(page)).length;
await page.evaluate(() => {
  send("a", { jsonrpc: "2.0", method: "test/one", params: { n: 1 } });
  send("a", { jsonrpc: "2.0", id: 7, method: "test/request" });
  send("a", { jsonrpc: "2.0", method: "ui/notifications/sandbox-anything", params: {} });
  send("a", { jsonrpc: "2.0", method: "ui/notifications/sandbox-resource-ready", params: { html: "<p>second</p>" } });
  send("a", { hello: "not json-rpc" });
  send("a", "a string");
  send("a", { jsonrpc: "2.0", id: 9, result: {} });
});
await pause(800);
const echoed = (await wire(page)).slice(base).filter((m) => m.data?.method === "test/echo").map((m) => m.data.params);
check(echoed.some((e) => e.method === "test/one") && echoed.some((e) => e.method === "test/request" && e.id === 7), "requests and notifications from the host reach the view");
check(echoed.some((e) => e.id === 9 && "result" in e), "and so do responses");
check(!echoed.some((e) => String(e.method ?? "").startsWith("ui/notifications/sandbox-")), "a sandbox message from the host is not forwarded to the view");
check(!echoed.some((e) => e.hello || typeof e === "string"), "a message that is not JSON-RPC is not forwarded");
check(!(await view.evaluate(() => document.body.innerText.includes("second"))), "a second sandbox-resource-ready does not replace the view");
check(echoed.every((e) => e.jsonrpc === "2.0"), "the proxy sent the view nothing of its own");
await view.evaluate(() => {
  const tell = (m) => parent.postMessage(m, "*");
  tell({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "x" } });
  tell({ jsonrpc: "2.0", method: "ui/notifications/size-changed", params: { height: 10 } });
  tell({ jsonrpc: "2.0", method: "ui/notifications/sandbox-proxy-ready", params: {} });
  tell({ jsonrpc: "2.0", method: "ui/notifications/sandbox-resource-ready", params: { html: "x" } });
  tell({ not: "rpc" });
  tell("string");
});
await pause(800);
const toHost = (await wire(page)).filter((m) => m.from === "a").slice(-12);
check(toHost.some((m) => m.data?.method === "tools/call" && m.data.id === 1 && m.origin === SANDBOX), "requests and notifications from the view reach the host, from the sandbox origin");
check(toHost.filter((m) => m.data?.method === READY).length === 1, `a sandbox message from the view is not forwarded (only the proxy's own ${READY} arrived)`);
check(!toHost.some((m) => m.data?.not || typeof m.data === "string"), "nor a message that is not JSON-RPC");
await context.close();

console.log("permissions and sandbox flags");
({ context, page } = await newPage());
await page.evaluate(() => embed("p", { allow: "camera; microphone; geolocation; clipboard-write" }));
await waitFor(page, (m) => m.data?.method === READY);
await page.evaluate(([html, signature]) => send("p", { jsonrpc: "2.0", method: "ui/notifications/sandbox-resource-ready", params: { html, signature, sandbox: "allow-scripts allow-same-origin allow-top-navigation allow-popups-to-escape-sandbox allow-downloads", permissions: { camera: {}, clipboardWrite: {}, payment: {} } } }), [VIEW(), sign()]);
await waitFor(page, (m) => m.data?.method === "test/report");
const pv = page.frames().find((f) => new URL(f.url()).pathname === "/view").frameElement();
const el = await pv;
check((await el.getAttribute("allow")) === "camera; clipboard-write", `permissions the resource declared and the host granted become the frame's allow (${await el.getAttribute("allow")})`);
check((await el.getAttribute("sandbox")) === "allow-scripts allow-same-origin", `a sandbox override keeps only the flags that are safe (${await el.getAttribute("sandbox")})`);
await context.close();

console.log("a view cannot ask for a policy the host did not sign");
({ context, page } = await newPage());
await page.evaluate(() => embed("w"));
await waitFor(page, (m) => m.data?.method === READY);
const sneaky = `<!doctype html><body><script>
  const wide = encodeURIComponent(JSON.stringify({ connectDomains: ["https://evil.example.com"] }));
  const child = document.createElement("iframe");
  child.src = "${SANDBOX}/view?host=" + encodeURIComponent("${HOST}") + "&csp=" + wide + "&sig=" + "0".repeat(64);
  // the view is on the sandbox origin, so it can reach the proxy and make a frame there
  parent.document.body.append(child);
  setTimeout(() => parent.postMessage({ jsonrpc: "2.0", method: "test/report", params: { child: "made" } }, "*"), 800);
<\/script>`;
await page.evaluate(([html, signature]) => send("w", { jsonrpc: "2.0", method: "ui/notifications/sandbox-resource-ready", params: { html, signature, sandbox: "allow-scripts allow-same-origin" } }), [sneaky, sign()]);
await waitFor(page, (m) => m.data?.method === "test/report");
await pause(500);
const children = page.frames().filter((f) => new URL(f.url()).pathname === "/view");
const refusedChild = children.find((f) => f.url().includes("evil.example.com"));
check(Boolean(refusedChild) && (await refusedChild.evaluate(() => document.body.innerText)).includes("not issued by the host"), "a same-origin view that makes a frame of its own with a wider policy is refused: the sandbox serves nothing for a policy the host did not sign");
await context.close();

console.log("who may embed it");
({ context, page } = await newPage());
const stranger = await (await context.request.get(`${SANDBOX}/?host=${encodeURIComponent("https://evil.example")}`)).status();
check(stranger === 403, "a page that names a host origin the sandbox does not serve is refused (403)");
const intruder = await context.newPage();
await intruder.goto(`${INTRUDER}/`);
await pause(1500);
const framed = intruder.frames().find((f) => f.url().startsWith(SANDBOX));
check(!framed || framed.url() === "chrome-error://chromewebdata/" || (await framed.evaluate(() => document.body?.innerText ?? "").catch(() => "")) === "", "another page cannot frame the proxy even naming the real host (frame-ancestors is the host's origin alone)");
const top = await context.newPage();
await top.goto(`${SANDBOX}/?host=${encodeURIComponent(HOST)}`);
await pause(500);
check((await top.locator("iframe").count()) === 0, "opened as a page of its own, the proxy does nothing");
await context.close();

console.log("two cards side by side");
({ context, page } = await newPage());
await page.evaluate(() => { embed("one"); embed("two"); });
await waitFor(page, (m) => m.from === "two" && m.data?.method === READY);
await waitFor(page, (m) => m.from === "one" && m.data?.method === READY);
const hello = (name) => `<!doctype html><body><script>parent.postMessage({jsonrpc:"2.0",method:"test/who",params:${JSON.stringify(name)}}, "*");<\/script>`;
await page.evaluate(([a, b, signature]) => { send("one", { jsonrpc: "2.0", method: "ui/notifications/sandbox-resource-ready", params: { html: a, signature } }); send("two", { jsonrpc: "2.0", method: "ui/notifications/sandbox-resource-ready", params: { html: b, signature } }); }, [hello("one"), hello("two"), sign()]);
await pause(1000);
const who = (await wire(page)).filter((m) => m.data?.method === "test/who").map((m) => `${m.from}:${m.data.params}`).sort();
check(JSON.stringify(who) === JSON.stringify(["one:one", "two:two"]), `each proxy carries its own view and messages arrive from the frame that sent them (${who})`);
await context.close();

await browser.close();
for (const server of servers) server.close();
finish();
