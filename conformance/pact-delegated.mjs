// SPDX-License-Identifier: AGPL-3.0-or-later
// PACT 1.0's Delegated profile (§5) against this host, through PACT's own client library (the suite's
// DeviceCodeClient, DelegatedA2AClient and verifyReceipt, conformance/pact-suite.mjs) and a real browser where
// the person signs in with Google (the Firebase Auth emulator), unticks a scope and presses Allow. The steps are
// the suite's delegated test, with 234's scopes and its own sign-in in place of the reference Brand's.
// Needs a stack with sign-in and PACT (AUTH=1 PACT=1).
// usage: PORT_BASE=… node conformance/pact-delegated.mjs
import { browser, chooseGoogleAccount, HOST, suite, watchErrors } from "./lib.mjs";
import { AUDIENCE, ISSUER, installSuite, personalAgent, suiteClient } from "./pact-suite.mjs";

const { check, finish } = suite("PACT Delegated");
installSuite();
const pact = await suiteClient();
const agent = await personalAgent();
const chromium = await browser();
const errors = [];
const signer = pact.createPlatformSigner({ issuer: ISSUER, privateJwk: JSON.stringify(agent.privateJwk) });
const sub = `e2e-delegated-${crypto.randomUUID()}`;
const getToken = () => signer.sign({ sub, aud: AUDIENCE });
const rejects = (promise, kind) => promise.then(() => false, (error) => error instanceof kind || error);
const EMAIL = "pact.person@example.com";

const screens = new URL("../docs/screens/", import.meta.url).pathname;

/** The person opens the agent's link, signs in to 234, leaves `scopes` ticked and decides; the page's outcome.
 * With `shot`, the consent page is captured in both themes first. */
// One browser for the person, as in life: signed in once, still signed in when the agent asks again (§5.5).
const person = await chromium.newContext({ viewport: { width: 390, height: 844 } });

async function approve(link, scopes, decision = "Allow", shot = false) {
  const page = await person.newPage();
  watchErrors(page, errors);
  await page.goto(link);
  const asked = await page.locator('[data-slot="title"]').innerText();
  let window;
  if (asked === "Sign in to connect your agent") {
    const popup = page.waitForEvent("popup");
    await page.getByRole("button", { name: "Continue with Google" }).click();
    window = await popup;
    await chooseGoogleAccount(window, EMAIL);
  }
  await page.locator('[data-slot="decision"]').waitFor({ timeout: 25000 }).catch(async (problem) => {
    const note = await page.locator('[data-slot="note"]').innerText().catch(() => "?");
    const state = { url: page.url(), popupClosed: window?.isClosed(), popupUrl: window && !window.isClosed() ? window.url().slice(0, 90) : "", note };
    throw new Error(`sign-in did not finish: ${JSON.stringify(state)} ${errors.slice(-3)}`, { cause: problem });
  });
  const title = await page.locator('[data-slot="title"]').innerText();
  for (const scheme of shot ? ["light", "dark"] : []) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.screenshot({ path: `${screens}pact-consent-${scheme}.png`, fullPage: true });
  }
  for (const box of await page.getByRole("checkbox").all()) {
    if (!scopes.includes(await box.getAttribute("value"))) await box.uncheck();
  }
  await page.getByRole("button", { name: decision, exact: true }).click();
  const outcome = await page.locator('[data-slot="device-done"]').getAttribute("data-outcome");
  await page.close();
  return { asked, title, outcome };
}

const found = await pact.fetchAgentCard(`${HOST}/a2a/234/.well-known/agent-card.json`);
const card = { card: found, url: pact.interfaceUrl(found) };
const scheme = pact.delegationScheme(card.card);
check(scheme !== undefined, "the card advertises delegation next to the personal-agent JWT");
check(
  JSON.stringify(scheme.scopes.map((s) => s.id)) === JSON.stringify(["memory:read", "memory:write", "payments"]),
  `with 234's scopes (${scheme.scopes.map((s) => s.id).join(", ")})`,
);
const metadata = await pact.fetchAuthorizationServerMetadata(scheme.metadataUrl);
check(metadata.token_endpoint === scheme.tokenUrl && metadata.device_authorization_endpoint === scheme.deviceAuthorizationUrl, "and RFC 8414 metadata that names the same endpoints");

console.log("\nwithout a token, a request that needs a scope steps up");
const plain = await new pact.DelegatedA2AClient({ url: card.url, getToken }).send("recall Mum");
check(plain.kind === "authRequired", `it is TASK_STATE_AUTH_REQUIRED (${plain.kind})`);
check(JSON.stringify(plain.missingScopes) === '["memory:read"]', `naming the missing scope (${plain.missingScopes})`);
let contextId = plain.task?.contextId;

console.log("\ndevice authorization");
const oauth = new pact.DeviceCodeClient({ scheme, clientId: ISSUER, getToken });
const wrong = new pact.DeviceCodeClient({ scheme, clientId: "https://other.example", getToken });
check((await rejects(wrong.start(["payments"]), pact.A2AHttpError)) === true, "a client_id that is not the agent's issuer is refused");
const authorization = await oauth.start(["memory:read", "memory:write", "payments"]);
check((await oauth.poll(authorization.deviceCode)).status === "pending", "the code is pending until the person decides");
const allowed = await approve(authorization.verificationUriComplete, ["memory:read", "payments"], "Allow", true);
check(allowed.asked === "Sign in to connect your agent", "a signed-out person is asked to sign in first");
check(allowed.title === `Allow ${new URL(ISSUER).host} to act for you at 234?`, `then names the agent and the Brand ("${allowed.title}")`);
check(allowed.outcome === "approved", "and the person allows it with one scope unticked");
const token = await oauth.waitForToken(authorization);
check(JSON.stringify(token.scopes.sort()) === '["memory:read","payments"]', `the token holds only the scopes left ticked (${token.scopes})`);
check((await rejects(oauth.poll(authorization.deviceCode), pact.OAuthError)) === true, "and the code cannot be used again");

console.log("\na message under the token");
const delegated = new pact.DelegatedA2AClient({ url: card.url, getToken, getDelegationToken: () => token.accessToken });
const recalled = await delegated.send("recall Mum", contextId ? { contextId } : {});
check(recalled.kind === "message" && recalled.message.contextId === contextId, "the stepped-up context carries on, as the person's account");
const claims = await pact.verifyReceipt(recalled.receipt, { jwks: metadata.jwks_uri, expected: { pa: ISSUER, brand: card.url } });
check(JSON.stringify(claims.scopesUsed) === '["memory:read"]', `with a receipt signed by the published key, for the scope used (${claims.scopesUsed})`);
check(claims.actions.some((a) => a.tool === "memory__recall"), "naming the tool that ran");

console.log("\nstep-up for a scope the token lacks");
const remember = await delegated.send("remember that I live in Yaba", { contextId });
check(remember.kind === "authRequired" && JSON.stringify(remember.missingScopes) === '["memory:write"]', `asks for memory:write (${remember.missingScopes})`);

console.log("\nrefresh, refusal and a token that does not hold");
const refreshed = await oauth.refresh(token.refreshToken);
check(JSON.stringify(refreshed.scopes.sort()) === JSON.stringify(token.scopes.sort()), "a refresh keeps the scopes");
check((await rejects(oauth.refresh(token.refreshToken), pact.OAuthError)) === true, "and the old refresh token is refused");
const second = await oauth.start(["payments"]);
const denied = await approve(second.verificationUriComplete, ["payments"], "Don't allow");
check(denied.asked.startsWith("Allow "), "a person still signed in goes straight to the decision");
check(denied.outcome === "denied", "a person who says no is told nothing was allowed");
const deniedPoll = await oauth.poll(second.deviceCode).then(() => "granted", (error) => error.error);
check(deniedPoll === "access_denied", `and the agent gets access_denied (${deniedPoll})`);
const forged = new pact.DelegatedA2AClient({ url: card.url, getToken, getDelegationToken: () => `${token.accessToken.slice(0, -4)}AAAA` });
check((await rejects(forged.send("hi"), pact.DelegationTokenRejectedError)) === true, "a delegation token that does not verify is rejected as invalid_token");

const unexpected = errors.filter((e) => !/Failed to load resource/.test(e));
check(unexpected.length === 0, `no page errors or policy violations ${unexpected.join("; ")}`);
agent.close();
await chromium.close();
finish();
