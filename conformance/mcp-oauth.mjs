// SPDX-License-Identifier: AGPL-3.0-or-later
// An outside MCP client connects to 234 the way Claude, ChatGPT or Cursor would: the official TypeScript client
// finds the authorization server from the 401, registers itself, sends the person to the consent page with PKCE,
// and the person signs in with Google (the Firebase Auth emulator) and presses Allow in a real browser. The
// client then calls the airtime connector through the gateway, as that account: a quote it makes is the
// account's, another account cannot see it, and a token for airtime does not open send-money. The 234 MCP
// Ready checker runs against the protected endpoint. Needs a stack with sign-in (AUTH=1).
// usage: node conformance/mcp-oauth.mjs
import { execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { createServer } from "node:http";
import { Client, StreamableHTTPClientTransport, UnauthorizedError } from "@modelcontextprotocol/client";
import { chromium } from "playwright";
import { freshLedger, HOST, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("MCP clients sign in with OAuth");
await freshLedger();
// The client's own loopback server, as a desktop MCP client receives its code.
const callbacks = [];
const loopback = createServer((req, res) => { callbacks.push(new URL(req.url, "http://127.0.0.1")); res.end("You can close this window."); });
await new Promise((done) => loopback.listen(0, "127.0.0.1", done));
const CALLBACK = `http://127.0.0.1:${loopback.address().port}/callback`;
const AIRTIME = `${HOST}/mcp/airtime`;
const run = randomBytes(3).toString("hex");
const browser = await chromium.launch({
  args: ["--host-resolver-rules=MAP fonts.googleapis.com ~NOTFOUND, MAP fonts.gstatic.com ~NOTFOUND, MAP unpkg.com ~NOTFOUND"],
});
const errors = [];

/** The client's own storage, as an MCP client keeps it: registration, verifier and tokens in memory. */
function provider(onRedirect) {
  const kept = {};
  return {
    kept,
    get redirectUrl() { return CALLBACK; },
    get clientMetadata() {
      return { client_name: "Conformance agent", redirect_uris: [CALLBACK], grant_types: ["authorization_code", "refresh_token"], response_types: ["code"], token_endpoint_auth_method: "none" };
    },
    state: () => "state-1",
    clientInformation: () => kept.client,
    saveClientInformation: (info) => { kept.client = info; },
    tokens: () => kept.tokens,
    saveTokens: (tokens) => { kept.tokens = tokens; },
    redirectToAuthorization: (url) => onRedirect(url),
    saveCodeVerifier: (verifier) => { kept.verifier = verifier; },
    codeVerifier: () => kept.verifier,
    saveDiscoveryState: (state) => { kept.discovery = state; },
    discoveryState: () => kept.discovery,
  };
}

/** What a person does in the emulator's "Google" window. */
async function chooseAccount(where, email) {
  await where.locator("#accounts-list").waitFor({ state: "visible", timeout: 15000 });
  const existing = where.locator("li.js-reuse-account", { hasText: email });
  if (await existing.count()) return existing.click();
  await where.locator("#add-account-button button").click();
  await where.locator("#email-input").fill(email);
  // The emulator's form now and then drops a click made right after the fill: press until the window closes.
  for (let tries = 0; tries < 3 && !where.isClosed(); tries += 1) {
    await where.locator("#sign-in").click().catch(() => {});
    await where.waitForEvent("close", { timeout: 5000 }).catch(() => {});
  }
}

/** The person opens the authorization URL, signs in, presses Allow; the callback URL the browser was sent to. */
async function approve(url, email, decision = "Allow") {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  watchErrors(page, errors);
  const warnings = [];
  page.on("console", (m) => ["warning", "error"].includes(m.type()) && warnings.push(m.text()));
  const before = callbacks.length;
  await page.goto(url.href);
  const title = await page.locator('[data-slot="title"]').innerText();
  check(title === "Sign in to connect Conformance agent", `a signed-out person is asked to sign in first ("${title}")`);
  const popup = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Continue with Google" }).click();
  const window = await popup;
  await chooseAccount(window, email);
  await page.getByRole("button", { name: "Allow" }).waitFor({ timeout: 25000 }).catch(async (problem) => {
    const state = { url: page.url().slice(0, 80), popupClosed: window.isClosed(), note: await page.locator('[data-slot="note"]').innerText().catch(() => "?") };
    throw new Error(`sign-in did not finish: ${JSON.stringify(state)} ${warnings.slice(-3)} ${errors.slice(-3)}`, { cause: problem });
  });
  check((await page.locator('[data-slot="title"]').innerText()) === "Allow Conformance agent to use 234?", "after sign-in the page asks to allow the client");
  const returns = await page.locator('[data-slot="redirect"]').innerText();
  check(returns === `Returns to ${new URL(CALLBACK).host}`, `and names where it returns ("${returns}")`);
  await page.getByRole("button", { name: decision }).click();
  await page.waitForURL(`${CALLBACK}**`, { timeout: 15000 }).catch(() => {});
  await context.close();
  return callbacks[before];
}

/** Connects as a new client: the first attempt is refused, the person approves, the second goes through. */
async function connect(url, email) {
  let authorizationUrl;
  const auth = provider((u) => { authorizationUrl = u; });
  const make = () => new StreamableHTTPClientTransport(new URL(url), { authProvider: auth });
  const transport = make();
  const client = new Client({ name: "oauth-conformance", version: "0.1.0" });
  const refused = await client.connect(transport).then(() => null, (e) => e);
  check(refused instanceof UnauthorizedError && authorizationUrl, "without a token the client is refused and sent to authorize");
  const callback = await approve(authorizationUrl, email);
  check(callback?.searchParams.get("state") === "state-1" && callback.searchParams.get("code"), "Allow returns a code and the state");
  await transport.finishAuth(callback.searchParams);
  const connected = new Client({ name: "oauth-conformance", version: "0.1.0" });
  await connected.connect(make());
  return { client: connected, auth, authorizationUrl };
}

const alice = await connect(AIRTIME, `alice.${run}@example.com`);
const asked = alice.authorizationUrl.searchParams;
check(asked.get("code_challenge_method") === "S256" && asked.get("resource") === AIRTIME && asked.get("scope") === "payments", `the client asked with PKCE, for ${asked.get("resource")} and ${asked.get("scope")}`);
check(alice.auth.kept.client?.client_id?.startsWith("234c_"), "the client registered itself (RFC 7591)");
const { tools } = await alice.client.listTools();
check(tools.some((t) => t.name === "create_airtime_quote"), `the client reaches the airtime connector (${tools.length} tools)`);

const made = await alice.client.callTool({ name: "create_airtime_quote", arguments: { network: "mtn", phone: "08031234567", amount_kobo: 50000, amount_as_user_said: "five hundred naira", idempotency_key: `oauth-${run}-1` } });
const quote = made.structuredContent?.quote;
check(quote?.phase === "awaiting_approval" && /^[0-9a-f]{64}$/.test(made._meta?.approvalToken ?? ""), "it makes a quote that waits for the person's approval");
const seen = await alice.client.callTool({ name: "get_quote_status", arguments: { quote_id: quote.id } });
check(!seen.isError, "the same account sees its quote");

const bob = await connect(AIRTIME, `bob.${run}@example.com`);
const hidden = await bob.client.callTool({ name: "get_quote_status", arguments: { quote_id: quote.id } });
check(hidden.isError === true && /QUOTE_NOT_FOUND/.test(hidden.content?.[0]?.text ?? ""), "another account cannot see it");

const token = alice.auth.kept.tokens.access_token;
const elsewhere = await fetch(`${HOST}/mcp/send-money`, { method: "POST", headers: { authorization: `Bearer ${token}`, "content-type": "application/json", accept: "application/json, text/event-stream" }, body: "{}" });
check(elsewhere.status === 401, `the airtime token does not open send-money (${elsewhere.status})`);

const ready = execFileSync("node", [new URL("../ready/cli.mjs", import.meta.url).pathname, AIRTIME, "--header", `Authorization: Bearer ${token}`, "--json"], { encoding: "utf8" });
const report = JSON.parse(ready);
const auth = report.results.filter((r) => r.id.startsWith("auth."));
check(report.failed === 0 && auth.length === 3 && auth.every((r) => r.ok), `234 MCP Ready passes with sign-in (${auth.map((r) => r.id).join(", ")})`);

await alice.client.close();
await bob.client.close();
check(errors.length === 0, `no page errors ${errors}`);
await browser.close();
loopback.close();
finish();
