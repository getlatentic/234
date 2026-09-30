// SPDX-License-Identifier: AGPL-3.0-or-later
// What the menu card runs need: the menu and the card page as the connector Worker serves them, a
// host page on the official AppBridge (card-states-host.html), a browser, and controls found by name.
import { mkdirSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { chromium } from "playwright";
import { hostPageHtml, settle } from "../card-checks.mjs";
import { CHECKOUT } from "../lib.mjs";

const here = fileURLToPath(new URL("..", import.meta.url));
export const screens = fileURLToPath(new URL("../../docs/screens/", import.meta.url));
mkdirSync(screens, { recursive: true });

let rpcId = 0;
export async function rpc(method, params) {
  const reply = await fetch(`${CHECKOUT}/food-order/mcp`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: ++rpcId, method, params }),
  });
  return (await reply.json()).result;
}

export const spawned = (ref = "qt-0123456789abcdef0123") => ({
  content: [{ type: "text", text: "Order ready to approve." }],
  structuredContent: { spawned: { ref } },
});
export const refusal = (text) => ({ isError: true, content: [{ type: "text", text }] });
export const naira = (kobo) => `₦${(kobo / 100).toLocaleString("en-US")}`;

export const controls = {
  add: (frame, name) => frame.getByRole("button", { name: `Add ${name}`, exact: true }),
  more: (frame, name) => frame.getByRole("button", { name: `One more ${name}`, exact: true }),
  less: (frame, name) => frame.getByRole("button", { name: `One less ${name}`, exact: true }),
  quantity: (frame, name) => frame.getByRole("group", { name, exact: true }).locator("output"),
  review: (frame) => frame.getByRole("button", { name: "Review order" }),
  search: (frame) => frame.getByRole("searchbox", { name: "Search the menu" }),
  area: (frame) => frame.getByLabel("Deliver to"),
  summary: (frame) => frame.locator('[data-slot="count"]').locator("xpath=..").innerText().then((text) => text.replace(/\s+/g, " ").trim()),
  total: (frame) => frame.locator('[data-slot="total"]'),
  rows: (frame) => frame.locator("li[data-item]"),
};

export async function startHarness() {
  const html = (await rpc("resources/read", { uri: "ui://food-order/menu.html" })).contents[0].text;
  const menu = await rpc("tools/call", { name: "search_menu", arguments: {} });
  const items = menu.structuredContent.items;
  const hostPage = await hostPageHtml();
  const bundle = await build({ entryPoints: [`${here}card-states-page.mjs`], bundle: true, format: "esm", write: false, minify: true, platform: "browser" });
  const server = createServer((req, res) => {
    const path = new URL(req.url, "http://x").pathname;
    if (path === "/") res.writeHead(200, { "content-type": "text/html" }).end(hostPage);
    else if (path === "/card-states-page.js") res.writeHead(200, { "content-type": "text/javascript" }).end(bundle.outputFiles[0].text);
    else res.writeHead(404).end();
  }).listen(0);
  const port = server.address().port;
  const browser = await chromium.launch();

  async function open({ scheme = "light", width = 400, result = menu, answer, hostContext, csp, viewport = { width: 480, height: 900 }, routes } = {}) {
    const context = await browser.newContext({ colorScheme: scheme, viewport, deviceScaleFactor: 2, reducedMotion: "reduce" });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    if (routes) await routes(page);
    await page.goto(`http://localhost:${port}/`);
    if (width !== 400) await page.addStyleTag({ content: `iframe { width: ${width}px !important }` });
    await page.evaluate((a) => window.__mount(a), { html, result, answer, scheme, hostContext, csp });
    await settle(page);
    await page.waitForTimeout(150);
    return { page, context, errors, frame: page.frameLocator("#card") };
  }

  return {
    menu,
    items,
    available: items.filter((i) => i.available),
    fee: menu.structuredContent.delivery_fee_kobo,
    open,
    withMenu: (patch) => ({ ...menu, structuredContent: { ...menu.structuredContent, ...patch } }),
    shot: (page, name, scheme) => page.locator("#card").screenshot().then((png) => writeFileSync(`${screens}menu-${name}-${scheme}.png`, png)),
    calls: (page) => page.evaluate(() => window.__log.filter((e) => e.kind === "calltool").map((e) => ({ name: e.name, args: e.args }))),
    close: async () => {
      await browser.close();
      server.close();
    },
  };
}
