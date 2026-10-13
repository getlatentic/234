// SPDX-License-Identifier: AGPL-3.0-or-later
// checks mode: interaction, accessibility and contrast checks of the Python-side card.
import { contrastReport } from "./card-checks.mjs";
import { check } from "./card-states-report.mjs";
import { copy, fixtures } from "./card-states-fixtures.mjs";

const calls = (page) => page.evaluate(() => window.__log.filter((e) => e.kind === "calltool").map((e) => ({ name: e.name, args: e.args })));

async function focusOrder(page, frame, presses) {
  const names = [];
  for (let i = 0; i < presses; i += 1) {
    await page.keyboard.press("Tab");
    names.push(await frame.locator(":focus").evaluate((el) => (el.getAttribute("aria-label") || el.labels?.[0]?.textContent || el.textContent || el.id || el.tagName).trim().slice(0, 30), undefined, { timeout: 1500 }).catch(() => null));
  }
  return names;
}

export async function checks({ open }, { only, schemes }) {
  for (const scheme of schemes) {
    console.log(`\ncontrast and errors, ${scheme}`);
    for (const key of Object.keys(fixtures).sort().filter((k) => only.test(k))) {
      const { page, context, errors, frame } = await open("python", key, scheme);
      const low = await frame.locator("body").evaluate(`(${contrastReport.toString()})()`);
      check(low.length === 0 && errors.length === 0, `${key}: text passes WCAG AA${low.length ? ` (${JSON.stringify(low.slice(0, 3))})` : ""}${errors.length ? ` errors ${errors}` : ""}`);
      const unnamed = await frame.locator("button, input").evaluateAll((els) => els.filter((el) => !(el.getAttribute("aria-label") || el.labels?.[0]?.textContent || el.textContent).trim()).length);
      check(unnamed === 0, `${key}: every button and input has an accessible name`);
      await context.close();
    }
  }

  console.log("\nApprove, Decline and a correction: no tick");
  for (const key of ["airtime/approve", "data/approve", "data/long-plan", "transfer/approve", "food/approve"]) {
    const { page, context, frame } = await open("python", key, "light", { answer: copy("airtime/checkout") });
    const approve = frame.getByRole("button", { name: "Approve" });
    check((await frame.getByRole("checkbox").count()) === 0 && (await approve.isEnabled()), `${key}: no tick, and Approve is enabled`);
    await approve.click();
    await page.waitForTimeout(300);
    const sent = (await calls(page)).find((c) => c.name === "approve_quote");
    check(sent?.args.readback_confirmed === true, `${key}: approve_quote carried readback_confirmed: true`);
    await context.close();
  }

  console.log("\npaying from the wallet");
  for (const key of ["airtime/approve", "transfer/approve", "food/approve"]) {
    const { context, frame } = await open("python", key, "light");
    check((await frame.getByRole("button", { name: /Pay from wallet/ }).count()) === 0, `${key}: no wallet offered when the quote carries none`);
    await context.close();
  }
  {
    const { page, context, frame } = await open("python", "airtime/approve-wallet", "light", { answer: copy("airtime/succeeded") });
    const pay = frame.getByRole("button", { name: "Pay from wallet" });
    check((await pay.count()) === 1 && (await pay.isEnabled()), "the wallet is offered with its balance");
    await pay.click();
    await frame.getByText("Airtime delivered").first().waitFor({ timeout: 5000 });
    const sent = (await calls(page)).find((c) => c.name === "approve_quote");
    check(sent?.args.funding === "wallet" && sent.args.readback_confirmed === true, "approve_quote carried funding: wallet");
    check(!(await page.evaluate(() => window.__log.some((e) => e.kind === "openlink"))), "and no checkout was opened");
    await context.close();
  }
  {
    const { page, context, frame } = await open("python", "airtime/approve-wallet", "light", { answer: copy("airtime/checkout") });
    await frame.getByRole("button", { name: "Approve" }).click();
    await page.waitForTimeout(300);
    const sent = (await calls(page)).find((c) => c.name === "approve_quote");
    check(sent && !("funding" in sent.args), "Approve beside it sends no funding: the checkout as before");
    await context.close();
  }
  for (const [code, text] of [
    ["WALLET_SHORT", "The wallet holds ₦200, less than this quote's ₦500. Nothing was taken."],
    ["WALLET_FROZEN", "This wallet is frozen, so it cannot pay. Nothing was taken."],
  ]) {
    const refused = { isError: true, content: [{ type: "text", text: `${code}: ${text}` }] };
    const { context, frame } = await open("python", "airtime/approve-wallet", "light", { answer: refused });
    await frame.getByRole("button", { name: /Pay from wallet/ }).click();
    const notice = frame.getByRole("alert");
    await notice.getByText(text).waitFor({ timeout: 5000 });
    check((await notice.innerText()).trim() === text, `${code}: the reason alone on the card, without the code`);
    check((await frame.getByRole("button", { name: /Pay from wallet/ }).count()) === 1, `${code}: and the card still offers its choices`);
    await context.close();
  }

  console.log("\ncorrection: declines the card and tells the chat");
  for (const key of ["airtime/approve", "transfer/approve"]) {
    const { page, context, frame } = await open("python", key, "light", { answer: copy("airtime/checkout") });
    const field = frame.getByRole("textbox", { name: "Correction" });
    check((await field.count()) === 1, `${key}: one field named Correction, already open`);
    await field.click();
    await field.fill("make it 2000 naira");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(400);
    check((await calls(page)).some((c) => c.name === "decline_quote"), `${key}: the card is declined`);
    check(await page.evaluate(() => window.__log.some((e) => e.kind === "message" && /^Correction to the card for .+₦.+: make it 2000 naira\. That card is declined: quote it again with this change\.$/.test(e.detail))), `${key}: the note reached the chat with the order it corrects`);
    await context.close();
  }
  {
    const { page, context, frame } = await open("python", "airtime/approve", "light");
    await frame.getByRole("button", { name: "Send correction" }).click();
    await page.waitForTimeout(300);
    check(!(await calls(page)).some((c) => c.name === "decline_quote"), "an empty correction does nothing");
    await context.close();
  }

  console.log("\na quote the connector does not know (the chat moved to an account)");
  for (const key of ["transfer/approve", "airtime/approve"]) {
    const lost = { isError: true, content: [{ type: "text", text: "QUOTE_NOT_FOUND: There is no quote qt-gone." }] };
    const { page, context, frame, errors } = await open("python", key, "light", { answer: lost });
    await frame.getByRole("button", { name: "Approve" }).click();
    await frame.getByText("No longer available").waitFor({ timeout: 5000 });
    const text = await frame.locator("body").innerText();
    check(!/QUOTE_NOT_FOUND|no quote/i.test(text), `${key}: the card says it is over, not the connector's error (${JSON.stringify(text.slice(0, 80))})`);
    check((await frame.getByRole("button").count()) === 0, `${key}: and offers nothing to press`);
    check((await calls(page)).filter((c) => c.name === "approve_quote").length === 1 && errors.length === 0, `${key}: one call was made, no page error`);
    await context.close();
  }

  console.log("\nkeyboard");
  for (const [key, expected] of [
    ["transfer/approve", ["Approve", "Decline"]],
    ["airtime/approve", ["Approve", "Decline", "Correction"]],
    ["airtime/approve-wallet", ["Approve", "Pay from wallet", "Decline", "Correction"]],
    ["airtime/checkout", ["Open checkout", "I closed it"]],
    ["transfer/otp", ["One-time code", "Confirm"]],
  ]) {
    const { page, context, frame } = await open("python", key, "light");
    const order = await focusOrder(page, frame, expected.length);
    check(expected.every((want, i) => (want instanceof RegExp ? want.test(order[i] ?? "") : (order[i] ?? "").startsWith(want))), `${key}: Tab order ${JSON.stringify(order)}`);
    const ring = await frame.locator(":focus").evaluate((el) => {
      const s = getComputedStyle(el);
      return s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2;
    }, undefined, { timeout: 1500 }).catch(() => false);
    check(ring, `${key}: the focused control shows a focus ring`);
    await context.close();
  }

  console.log("\nOTP form");
  {
    const { page, context, frame } = await open("python", "transfer/otp", "light", { answer: copy("transfer/succeeded") });
    await frame.getByLabel("Code").fill("123456");
    await frame.getByRole("button", { name: "Confirm" }).click();
    await page.waitForTimeout(300);
    const sent = (await calls(page)).find((c) => c.name === "submit_otp");
    if (!sent) console.log("   calls:", JSON.stringify(await calls(page)));
    check(sent?.args.otp === "123456", "submit_otp carried the typed code");
    check((await frame.getByText("Transfer sent").count()) > 0, "the card showed the receipt from the answer");
    await context.close();
  }
  {
    const { page, context, frame } = await open("python", "transfer/otp", "light", { answer: copy("transfer/succeeded") });
    await frame.getByLabel("Code").fill("654321");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(300);
    check((await calls(page)).some((c) => c.name === "submit_otp" && c.args.otp === "654321"), "Enter in the code field sends the code (the sandbox allows no form submission)");
    await context.close();
  }
  {
    const { context, frame } = await open("python", "transfer/otp-rejected", "light");
    check((await frame.getByRole("alert").innerText()).trim().length > 0, "a rejected code shows in an alert");
    await context.close();
  }
}
