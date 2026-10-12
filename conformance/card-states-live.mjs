// SPDX-License-Identifier: AGPL-3.0-or-later
// live mode: the card wired through the bridge to running Workers (PLAIN/OTP/NOPAY urls as in
// card-states-capture.mjs; PLAIN needs a small FOOD_STEP_SECONDS).
import { settle } from "./card-checks.mjs";
import { check } from "./card-states-report.mjs";

const WORKERS = {
  plain: process.env.PLAIN ?? "http://localhost:8890",
  otp: process.env.OTP ?? "http://localhost:8891",
  nopay: process.env.NOPAY ?? "http://localhost:8892",
};
let rpcId = 0;
const rpc = async (base, connector, name, args) => {
  const body = { jsonrpc: "2.0", id: ++rpcId, method: "tools/call", params: { name, arguments: args } };
  const res = await fetch(`${base}/${connector}/mcp`, { method: "POST", headers: { "content-type": "application/json", accept: "application/json" }, body: JSON.stringify(body) });
  return (await res.json()).result;
};
const runKey = Math.random().toString(36).slice(2, 8);

const liveOpener = ({ browser, port: PORT }) =>
  async (base, connector, tool, args) => {
    const made = await rpc(base, connector, tool, { ...args, idempotency_key: `live-${runKey}-${++rpcId}` });
    if (made.isError) throw new Error(`${connector} refused the quote: ${made.content?.[0]?.text}`);
    const context = await browser.newContext({ colorScheme: "light", viewport: { width: 400, height: 900 }, reducedMotion: "reduce" });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.exposeFunction("__forward", (name, callArgs) => rpc(base, connector, name, callArgs));
    await page.goto(`http://localhost:${PORT}/`);
    const cardHtml = await (await fetch(`http://localhost:${PORT}/card/python`)).text();
    await page.evaluate((a) => window.__mount(a), { html: cardHtml, result: made, scheme: "light" });
    await settle(page);
    return { page, context, errors, frame: page.frameLocator("#card"), made };
  };
const shows = (frame, text, ms = 15000) => frame.getByText(text).first().waitFor({ timeout: ms }).then(() => true, () => false);
const paySim = (base, page) =>
  page.evaluate(() => window.__log.find((e) => e.kind === "openlink")?.url).then((url) => fetch(`${base}${new URL(url).pathname}/pay`, { method: "POST" }));

export async function live(harness) {
  const openLive = liveOpener(harness);
  console.log("airtime: Approve, checkout, delivered");
  {
    const { page, context, errors, frame } = await openLive(WORKERS.plain, "airtime", "create_airtime_quote", { network: "mtn", phone: "08011111111", amount_kobo: 50_000, amount_as_user_said: "N500" });
    await frame.getByRole("button", { name: "Approve" }).click();
    check(await shows(frame, "Open checkout"), "the server accepted the approval and moved to checkout");
    check(await page.evaluate(() => window.__log.some((e) => e.kind === "openlink")), "the card asked the host to open the checkout");
    await paySim(WORKERS.plain, page);
    check(await shows(frame, "Airtime delivered"), "polling ended on the delivered receipt");
    check(errors.length === 0, `no page errors ${errors}`);
    await context.close();
  }
  console.log("airtime: refund due");
  {
    const { page, context, frame } = await openLive(WORKERS.plain, "airtime", "create_airtime_quote", { network: "mtn", phone: "100000000000", amount_kobo: 50_000, amount_as_user_said: "N500" });
    await frame.getByRole("button", { name: "Approve" }).click();
    await shows(frame, "Open checkout");
    await paySim(WORKERS.plain, page);
    check(await shows(frame, "Refunding ₦500"), "a paid order VTpass could not deliver shows it is refunding");
    await context.close();
  }
  console.log("transfer with a one-time code");
  {
    const { frame, context } = await openLive(WORKERS.otp, "send-money", "create_transfer_quote", { account_number: "0000000000", bank_code: "057", amount_kobo: 2_500_000, amount_as_user_said: "25k", narration: "Rent share" });
    await frame.getByRole("button", { name: "Approve" }).click();
    check(await shows(frame, "Confirm"), "approval moved the card to the code step");
    await frame.getByLabel("One-time code").fill("000000");
    await frame.getByRole("button", { name: "Confirm" }).click();
    check(await frame.getByRole("alert").waitFor({ timeout: 8000 }).then(() => true, () => false), "a wrong code shows an alert");
    check(await frame.getByLabel("One-time code").evaluate((el) => el === el.getRootNode().activeElement), "the field is focused again for the next try");
    const hint = await frame.getByText(/Simulated code/).innerText();
    await frame.getByLabel("One-time code").fill(hint.match(/\d{4,}/)[0]);
    await frame.getByLabel("One-time code").press("Enter");
    check(await shows(frame, "Transfer sent", 8000), "the right code ended on the Transfer sent receipt");
    await context.close();
  }
  console.log("transfer on an account that cannot make payouts");
  {
    const { frame, context } = await openLive(WORKERS.nopay, "send-money", "create_transfer_quote", { account_number: "0000000000", bank_code: "057", amount_kobo: 2_500_000, amount_as_user_said: "25k" });
    await frame.getByRole("button", { name: "Approve" }).click();
    check(await shows(frame, "Not sent", 8000), "the unavailable state shows Not sent with the reason");
    check((await frame.getByRole("button").count()) === 0, "there is no button left to press");
    await context.close();
  }
  console.log("food order to delivery");
  {
    const { page, context, frame } = await openLive(WORKERS.plain, "food-order", "create_food_quote", { items: [{ item_id: "beef-suya", quantity: 1 }], delivery_area: "Surulere" });
    await frame.getByRole("button", { name: "Approve" }).click();
    await shows(frame, "Open checkout");
    await paySim(WORKERS.plain, page);
    check(await shows(frame, "Order accepted", 10000), "the tracker appeared after payment");
    check(await frame.locator('[aria-current="step"]').count() === 1, "exactly one step is marked current");
    check(await shows(frame, "Order delivered", 40000), "the tracker ended on the Order delivered receipt");
    await context.close();
  }
}
