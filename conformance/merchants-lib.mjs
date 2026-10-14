// SPDX-License-Identifier: AGPL-3.0-or-later
// Shared by the browser suites of the merchants connector: a browser that blocks the outside fonts, and a person
// in a browser context of their own, signed in through the host's own endpoint with a token from the Firebase Auth
// emulator (the stack started with AUTH=1), or a visitor.
import { randomBytes } from "node:crypto";
import { chromium } from "playwright";
import { csrfOf, HOST, openHome, watchErrors } from "./lib.mjs";

const base = Number(process.env.PORT_BASE ?? 8900);
const EMULATOR = `localhost:${base + 7}`;
const run = randomBytes(3).toString("hex");

export async function browserOf() {
  const browser = await chromium.launch({
    args: ["--host-resolver-rules=MAP fonts.googleapis.com ~NOTFOUND, MAP fonts.gstatic.com ~NOTFOUND, MAP unpkg.com ~NOTFOUND"],
  });
  return { browser, errors: [] };
}

async function emulatorToken(email) {
  const identity = JSON.stringify({ sub: `uid-${email}`, email, email_verified: true });
  const form = new URLSearchParams({ id_token: identity, providerId: "google.com" }).toString();
  const reply = await fetch(`http://${EMULATOR}/identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key=fake-api-key-for-the-emulator`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ postBody: form, requestUri: "http://localhost", returnIdpCredential: true, returnSecureToken: true }),
  });
  return (await reply.json()).idToken;
}

/** A browser of its own for a person; `who` signs them in as that account, none leaves a visitor. */
export async function person(browser, errors, who, options = {}) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, ...options });
  const page = await context.newPage();
  watchErrors(page, errors);
  await openHome(page);
  if (who) {
    const csrf = await csrfOf(page);
    const signed = await context.request.post(`${HOST}/auth/session`, { data: { idToken: await emulatorToken(`${who}.${run}@example.com`) }, headers: { "X-CSRFToken": csrf } });
    if (signed.status() !== 200) throw new Error(`sign-in refused: ${signed.status()}`);
    await openHome(page);
  }
  return { context, page };
}
