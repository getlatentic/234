// SPDX-License-Identifier: AGPL-3.0-or-later
// 234 as a person's own agent at another Brand, against PACT's own reference Provider and its Skyline Brand
// app (the pinned repository, conformance/pact-suite.mjs), started here: 234 registers itself at the Provider
// with a JWT its own key signs, and a person in 234's chat asks Skyline about a flight (PACT Identity), then
// about their upcoming flights, which Skyline answers only with their permission. A visitor is told to sign in
// to 234 first; once signed in, the sign-in card opens the Brand's own login, the person allows one scope, the
// card sees the Brand issue the token and says so in the chat, and 234 asks again and gets the answer with a
// receipt it checks. Rebooking then steps up for the scope left out, and the person disconnects Skyline in
// Connected apps.
// Needs a stack with AUTH=1 and REACH=1 (tools/stack.sh reach_vars). usage: PORT_BASE=… node conformance/pact-reach.mjs
import { spawn } from "node:child_process";
import { createPrivateKey, createSign, randomUUID } from "node:crypto";
import { readFileSync, rmSync } from "node:fs";
import { browser, chooseGoogleAccount, HOST, openDrawer, popupWhenRelayReady, say, settled, startChat, suite, watchErrors } from "./lib.mjs";
import { installReference, PNPM, SUITE_DIR } from "./pact-suite.mjs";

const { check, finish } = suite("234 acts for a person at another Brand (PACT)");
const base = Number(process.env.PORT_BASE ?? 8900);
const [providerPort, brandPort, databasePort] = [base + 12, base + 13, base + 14];
const PROVIDER = `http://localhost:${providerPort}`;
const BRAND = `http://localhost:${brandPort}`;
const SKYLINE = "01M3R53Q5SZQ6FQSMSDBSSREAA";
const state = new URL(`../.stack/${base}/`, import.meta.url).pathname;
const database = `postgres://postgres:postgres@127.0.0.1:${databasePort}/postgres`;
const started = [];
const EMAIL = "reach.person@example.com";

function run(args, env, label) {
  const child = spawn("npx", [...PNPM, ...args], { cwd: SUITE_DIR, env: { ...process.env, ...env }, detached: true, stdio: ["ignore", "pipe", "pipe"] });
  child.output = "";
  for (const stream of [child.stdout, child.stderr]) stream.on("data", (chunk) => { child.output = (child.output + chunk).slice(-4000); });
  child.label = label;
  started.push(child);
  return child;
}

async function finished(child) {
  const code = await new Promise((done) => child.on("close", done));
  if (code !== 0) throw new Error(`${child.label} failed (${code}):\n${child.output}`);
}

async function answers(url, label, seconds = 240) {
  for (let i = 0; i < seconds; i += 1) {
    if (await fetch(url).then((r) => r.status < 500, () => false)) return;
    await new Promise((done) => setTimeout(done, 1000));
  }
  throw new Error(`${label} did not answer at ${url}:\n${started.find((c) => c.label === label)?.output ?? ""}`);
}

function stopAll() {
  for (const child of started) {
    try {
      process.kill(-child.pid, "SIGTERM");
    } catch {}
  }
}

function registrationJwt(endpoint) {
  const jwk = JSON.parse(readFileSync(`${state}pact-agent-key.json`, "utf8"));
  const b64 = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
  const now = Math.floor(Date.now() / 1000);
  const claims = { iss: HOST, sub: HOST, aud: endpoint, iat: now, exp: now + 120, jti: randomUUID() };
  const signed = `${b64({ alg: "ES256", kid: jwk.kid, typ: "JWT" })}.${b64(claims)}`;
  const key = createPrivateKey({ key: jwk, format: "jwk" });
  const signature = createSign("SHA256").update(signed).sign({ key, dsaEncoding: "ieee-p1363" }, "base64url");
  return `${signed}.${signature}`;
}

async function startReference() {
  installReference();
  rmSync(`${state}pact-provider-db`, { recursive: true, force: true });
  run(["--filter", "@openpactprotocol/provider", "db:pglite"], { PGLITE_PORT: String(databasePort), PGLITE_DATA_DIR: `${state}pact-provider-db` }, "database");
  await new Promise((done) => setTimeout(done, 3000));
  const db = { DATABASE_URL: database, DATABASE_POOL_MAX: "1" };
  await finished(run(["--filter", "@openpactprotocol/provider", "db:migrate"], db, "migrate"));
  await finished(run(["--filter", "@openpactprotocol/provider", "db:seed"], { ...db, PA_ISSUER: "http://localhost:1/unused", SEED_DEMO_PLATFORM: "false" }, "seed"));
  const provider = { ...db, PROVIDER_URL: PROVIDER, A2A_AUDIENCE: `${PROVIDER}/a2a`, DELEGATION_ENABLED: "1", BRAND_URL: BRAND, CONSENT_ORIGIN: PROVIDER };
  run(["--filter", "@openpactprotocol/provider", "exec", "next", "dev", "-p", String(providerPort)], provider, "provider");
  run(["--filter", "@openpactprotocol/brand", "dev"], { PORT: String(brandPort), BRAND_URL: BRAND, PROVIDER_URL: PROVIDER, CONSENT_ORIGIN: PROVIDER }, "brand");
  await answers(`${PROVIDER}/api/health`, "provider");
  await answers(`${BRAND}/`, "brand");
  await answers(`${PROVIDER}/a2a/${SKYLINE}/.well-known/agent-card.json`, "provider");
}

/** The person signs in at Skyline (the reference Brand's demo account), and allows `scopes` on the consent page. */
async function signInAtSkyline(page, scopes) {
  await page.getByLabel(/email/i).fill("alex.rivera@example.com");
  await page.getByLabel(/password/i).fill("skyline");
  await page.getByRole("button", { name: "Sign in" }).click();
  // The Brand's "Signing in…" page posts its single-use assertion to the Provider's consent page by itself.
  await page.locator("#allow").waitFor({ timeout: 30000 });
  const boxes = page.locator('input[type="checkbox"][name="scope"]');
  const asked = await boxes.evaluateAll((all) => all.map((box) => box.value));
  for (const box of await boxes.all()) {
    if (!scopes.includes(await box.getAttribute("value"))) await box.uncheck();
  }
  await page.locator("#allow").click();
  await page.waitForURL(/status=approved/, { timeout: 30000 });
  return asked;
}

const screens = new URL("../docs/screens/", import.meta.url).pathname;
const lastReply = (page) => page.locator("assistant-text").last().innerText();
const lastCard = (page) => page.frameLocator("card-frame iframe").last().frameLocator("iframe");

try {
  await startReference();
  const endpoint = `${PROVIDER}/api/platforms`;
  const registered = await fetch(endpoint, {
    method: "POST",
    headers: { authorization: `Bearer ${registrationJwt(endpoint)}`, "content-type": "application/json" },
    body: JSON.stringify({ name: "234", jwksUri: `${HOST}/.well-known/jwks.json` }),
  });
  check(registered.status === 201, `234 registers itself at the Provider with a JWT its own key signs (${registered.status})`);
  const jwks = await (await fetch(`${HOST}/.well-known/jwks.json`)).json();
  check(jwks.keys.length === 1 && !("d" in jwks.keys[0]), "and publishes only the public half of that key");

  const chromium = await browser();
  const errors = [];
  const context = await chromium.newContext({ viewport: { width: 420, height: 860 } });
  const page = await context.newPage();
  watchErrors(page, errors);

  console.log("\nPACT Identity: a question about a flight");
  await startChat(page, "ask skyline Is my Friday flight on time?");
  await settled(page, 60000);
  const asked = await lastReply(page);
  check(/confirmation code/i.test(asked), `Skyline's own agent answers through 234 ("${asked.slice(0, 90)}")`);
  await say(page, "ask skyline ABC123");
  await settled(page, 60000);
  const answered = await lastReply(page);
  check(/SK 482/.test(answered) && /delayed/.test(answered), `and the conversation carries on there (${answered.slice(0, 90)})`);

  console.log("\nPACT Delegated: upcoming flights need the person's permission, which only an account gives");
  await say(page, "ask skyline Can you check my upcoming flights?");
  await settled(page, 60000);
  const visitor = await lastReply(page);
  check(/only someone signed in to 234 can give it/.test(visitor) && (await page.locator("card-frame").count()) === 0, `a visitor is told to sign in to 234 first, with no card (${visitor.slice(0, 120)})`);
  await openDrawer(page);
  const google = await popupWhenRelayReady(page, () => page.getByRole("button", { name: "Continue with Google" }).click(), () => openDrawer(page));
  await chooseGoogleAccount(google, EMAIL);
  await page.locator('chat-account [data-slot="email"]').waitFor({ timeout: 25000 });
  await page.keyboard.press("Escape");
  await say(page, "ask skyline Can you check my upcoming flights?");
  const signIn = lastCard(page).getByRole("button", { name: "Sign in with Skyline Airways" });
  await signIn.waitFor({ timeout: 60000 });
  for (const scheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.waitForTimeout(400);
    await page.locator("card-frame").last().screenshot({ path: `${screens}reach-sign-in-card-${scheme}.png` });
  }
  await page.emulateMedia({ colorScheme: "light" });
  const title = await lastCard(page).locator('[data-slot="title"]').innerText();
  check(title === "Skyline Airways needs your permission", `the card names the Brand and its one action ("${title}")`);
  const opened = context.waitForEvent("page", { timeout: 20000 });
  await signIn.click();
  const login = await opened;
  check(login.url().startsWith(`${BRAND}/login`), `the card opens Skyline's own sign-in page (${login.url().slice(0, 50)})`);
  const consented = await signInAtSkyline(login, ["flights:upcoming:read"]);
  check(consented.join() === "flights:upcoming:read", `Skyline shows what 234 asked for on its own consent page (${consented.join("; ")}), and the person allows it`);
  await lastCard(page).getByText("Connected to Skyline Airways").waitFor({ timeout: 30000 });
  check(true, "the card sees Skyline issue the token");
  await page.getByText("I've signed in with Skyline Airways.").first().waitFor({ timeout: 20000 });
  await settled(page, 60000);
  check((await page.getByText("I've signed in with Skyline Airways.").count()) === 1, "and says so in the chat once");
  const delegated = await lastReply(page);
  check(/receipt checks out/.test(delegated), `234 asks again, as the person, and checks Skyline's receipt (${delegated.slice(0, 120)})`);

  console.log("\nstep-up: rebooking needs the scope the person left out");
  await say(page, "ask skyline Please rebook me onto SK 318");
  await page.locator("card-frame").nth(1).waitFor({ timeout: 60000 });
  await lastCard(page).getByRole("button", { name: "Sign in with Skyline Airways" }).waitFor({ timeout: 30000 });
  check(true, "a request beyond what the person allowed shows a new sign-in card");

  console.log("\nthe person disconnects Skyline in Connected apps");
  await openDrawer(page);
  await page.getByRole("button", { name: "Connected apps" }).click();
  const sheet = page.locator("chat-connected dialog[open]");
  const row = sheet.locator('[data-slot="row"]', { hasText: "Skyline Airways" });
  await row.waitFor({ timeout: 10000 });
  page.once("dialog", (dialog) => dialog.accept());
  await row.getByRole("button", { name: "Disconnect Skyline Airways" }).click();
  await row.waitFor({ state: "detached", timeout: 10000 });
  const note = await sheet.locator('[data-slot="note"]').innerText();
  check(note === "Skyline Airways doesn't let 234 end it there. You can in your Skyline Airways settings.", `PACT's reference Provider offers no revocation endpoint, so the person is told where to end it ("${note}")`);
  await sheet.getByRole("button", { name: "Close" }).click();
  await page.keyboard.press("Escape");
  await say(page, "ask skyline Can you check my upcoming flights?");
  await page.locator("card-frame").nth(2).waitFor({ timeout: 60000 });
  check(true, "234 forgot its tokens: the next request asks for the person's permission again");

  const unexpected = errors.filter((e) => !/Failed to load resource/.test(e));
  check(unexpected.length === 0, `no page errors or policy violations ${unexpected.join("; ")}`);
  await chromium.close();
} finally {
  stopAll();
}
finish();
