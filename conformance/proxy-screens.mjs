// SPDX-License-Identifier: AGPL-3.0-or-later
// The screenshots of the card behind the sandbox proxy, light and dark: a card in the proxy, a card that says where it
// loads content from, full screen through the proxy, and the state the approval card is left in when the popup cannot
// run and the link is used instead.
//
// needs the stack with the rig: `PAYSTACK_RIG=fake tools/up.sh`. usage: PORT_BASE=8920 node conformance/proxy-screens.mjs
import { mkdirSync } from "node:fs";
import { browser, cardIn, freshLedger, pause, startChat } from "./lib.mjs";
import { askForTheMenu, menuFrame } from "./menu-chat-lib.mjs";
import { paystackStub } from "./paystack-stub.mjs";

const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
await freshLedger();
const chromium = await browser();

for (const scheme of ["light", "dark"]) {
  const shot = (page, name) => page.screenshot({ path: `${screens}proxy-${name}-${scheme}.png` });
  const context = await chromium.newContext({ viewport: { width: 420, height: 820 }, colorScheme: scheme });
  await paystackStub(context, { script: "missing" });

  const menu = await context.newPage();
  await askForTheMenu(menu);
  await menuFrame(menu).getByRole("button", { name: "Add Zobo, 500ml", exact: true }).click();
  await pause(400);
  await shot(menu, "card");
  await menuFrame(menu).getByRole("button", { name: "Full screen", exact: true }).click();
  await pause(700);
  await shot(menu, "fullscreen");

  const pay = await context.newPage();
  await startChat(pay, "Pay ₦2,500 to Demo Kitchen for lunch");
  const card = cardIn(pay);
  await card.getByRole("button", { name: /Approve/ }).waitFor({ timeout: 20000 });
  await pause(500);
  await shot(pay, "domains");
  const tab = context.waitForEvent("page", { timeout: 15000 });
  await card.getByRole("button", { name: /Approve/ }).click();
  await (await tab).close();
  await card.getByRole("button", { name: /Open checkout/ }).waitFor({ timeout: 10000 });
  await pause(800);
  await shot(pay, "popup-fallback");
  await context.close();
}
await chromium.close();
console.log("screenshots written to docs/screens/proxy-*");
