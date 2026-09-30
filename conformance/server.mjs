// SPDX-License-Identifier: AGPL-3.0-or-later
// The host's server side for the conformance run: a static page, and the official TypeScript MCP client
// talking to the Python Worker. The page never reaches the Worker itself, as the Django host's page won't.
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { randomBytes } from "node:crypto";
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import { isToolVisibilityModelOnly } from "@modelcontextprotocol/ext-apps/app-bridge";
import { build } from "esbuild";

const WORKER = process.env.CHECKOUT_URL ?? "http://localhost:8900";
const PORT = Number(process.env.PORT ?? 8930);
const here = new URL(".", import.meta.url).pathname;

const client = new Client({ name: "conformance-host", version: "0.1.0" });
await client.connect(new StreamableHTTPClientTransport(new URL(`${WORKER}/paystack-pay/mcp`)));
const tools = (await client.listTools()).tools;

const bundle = await build({
  entryPoints: [`${here}host-page.js`], bundle: true, format: "esm", write: false, minify: true, platform: "browser",
});

const readBody = async (req) => {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {};
};

const routes = {
  "GET /": async () => ["text/html", await readFile(`${here}host.html`)],
  "GET /host-page.js": async () => ["text/javascript", bundle.outputFiles[0].text],
  "POST /api/quote": async () => {
    const result = await client.callTool({
      name: "create_payment_quote",
      arguments: {
        amount_kobo: 250000, amount_as_user_said: "₦2,500", description: "Lunch", merchant: "Demo Kitchen",
        idempotency_key: `conf-${randomBytes(6).toString("hex")}`,
      },
    });
    return ["application/json", JSON.stringify(result)];
  },
  "POST /api/call": async (req) => {
    const { name, arguments: args } = await readBody(req);
    const tool = tools.find((t) => t.name === name);
    if (!tool) return ["application/json", JSON.stringify({ refused: `There is no tool ${name}.` })];
    if (isToolVisibilityModelOnly(tool)) return ["application/json", JSON.stringify({ refused: `${name} is not available to cards.` })];
    return ["application/json", JSON.stringify(await client.callTool({ name, arguments: args }))];
  },
  "GET /api/card": async (req) => {
    const uri = new URL(req.url, "http://x").searchParams.get("uri");
    const read = await client.readResource({ uri });
    return ["text/html", read.contents[0].text];
  },
};

createServer(async (req, res) => {
  const key = `${req.method} ${new URL(req.url, "http://x").pathname}`;
  const route = routes[key];
  if (!route) { res.writeHead(404).end(); return; }
  try {
    const [type, body] = await route(req);
    res.writeHead(200, { "content-type": type }).end(body);
  } catch (error) {
    res.writeHead(500, { "content-type": "text/plain" }).end(String(error));
  }
}).listen(PORT, () => console.log(`conformance host on http://localhost:${PORT}`));
