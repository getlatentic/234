// SPDX-License-Identifier: AGPL-3.0-or-later
// The page every mode runs in: the card under test in a sandboxed iframe on the official AppBridge, served
// from a local port, and a browser to open it in.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { chromium } from "playwright";
import { hostPageHtml, settle } from "./card-checks.mjs";
import { fixtures, refreshed } from "./card-states-fixtures.mjs";

const here = fileURLToPath(new URL(".", import.meta.url));
export const root = fileURLToPath(new URL("../", import.meta.url));
export const CARDS = {
  python: { prefix: "card", file: `${root}checkout/src/checkout/card/card.html` },
  react: { prefix: "react", file: `${root}checkout/src/checkout/card/react-card.html` },
};

export async function startHarness(PORT) {
  const bundle = await build({
    entryPoints: [`${here}card-states-page.mjs`], bundle: true, format: "esm", write: false, minify: true, platform: "browser",
  });
  const html = await hostPageHtml();
  const server = createServer(async (req, res) => {
    const path = new URL(req.url, "http://x").pathname;
    const card = /^\/card\/(\w+)$/.exec(path)?.[1];
    if (path === "/") res.writeHead(200, { "content-type": "text/html" }).end(html);
    else if (path === "/card-states-page.js") res.writeHead(200, { "content-type": "text/javascript" }).end(bundle.outputFiles[0].text);
    else if (card && CARDS[card]) res.writeHead(200, { "content-type": "text/html" }).end(await readFile(CARDS[card].file));
    else res.writeHead(404).end();
  }).listen(PORT);

  const browser = await chromium.launch();
  async function open(cardName, key, scheme, extra = {}) {
    const context = await browser.newContext({ colorScheme: scheme, viewport: { width: 400, height: 900 }, deviceScaleFactor: 2, reducedMotion: "reduce" });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    await page.goto(`http://localhost:${PORT}/`);
    const cardHtml = await (await fetch(`http://localhost:${PORT}/card/${cardName}`)).text();
    const { notice, ...result } = refreshed(key, fixtures[key]);
    await page.evaluate((a) => window.__mount(a), { html: cardHtml, result, scheme, notice, ...extra });
    await settle(page);
    await page.waitForTimeout(150);
    return { page, context, errors, frame: page.frameLocator("#card") };
  }
  const close = async () => {
    await browser.close();
    server.close();
  };
  return { browser, open, port: PORT, close };
}
