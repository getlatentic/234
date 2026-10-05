// SPDX-License-Identifier: AGPL-3.0-or-later
// A stateless MCP server over Streamable HTTP (JSON responses), with a tool list the test chooses.
import { createServer } from "node:http";

export function fakeServer({ tools, requireSignIn = false, repeatsResult = true, instructions = "Quote first; the person approves every payment in the card." }) {
  const sent = new Map();
  const handle = (msg) => {
    if (msg.method === "initialize") {
      return { protocolVersion: msg.params.protocolVersion, capabilities: { tools: {} }, serverInfo: { name: "fake", version: "1.0.0" }, instructions };
    }
    if (msg.method === "tools/list") return { tools };
    if (msg.method === "tools/call") {
      const tool = tools.find((t) => t.name === msg.params.name);
      if (!tool) return { isError: true, content: [{ type: "text", text: "unknown tool" }] };
      const missing = (tool.inputSchema.required ?? []).filter((k) => !(k in (msg.params.arguments ?? {})));
      if (missing.length) return { isError: true, content: [{ type: "text", text: `missing ${missing}` }] };
      const key = repeatsResult ? JSON.stringify(msg.params) : String(sent.size);
      if (!sent.has(key)) sent.set(key, sent.size + 1);
      return { content: [{ type: "text", text: "ok" }], structuredContent: { id: sent.get(key) } };
    }
    return {};
  };
  const server = createServer((req, res) => {
    if (req.url === "/.well-known/oauth-protected-resource") {
      res.setHeader("content-type", "application/json");
      return res.end(JSON.stringify({ resource: "x", authorization_servers: ["https://auth.example"], scopes_supported: ["pay"] }));
    }
    if (req.method !== "POST") return void res.writeHead(405).end();
    if (requireSignIn && !req.headers.authorization) {
      return void res.writeHead(401, { "www-authenticate": 'Bearer resource_metadata="' + `http://127.0.0.1:${server.address().port}/.well-known/oauth-protected-resource"` }).end();
    }
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const msg = JSON.parse(body);
      if (msg.id === undefined) return void res.writeHead(202).end();
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: handle(msg) }));
    });
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ url: `http://127.0.0.1:${server.address().port}/mcp`, close: () => server.close() })));
}

const tool = (name, props, extra = {}) => ({
  name,
  description: `${name.replaceAll("_", " ")} for the person who asked, and nothing else.`,
  inputSchema: { type: "object", properties: props, required: Object.keys(props) },
  annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true },
  ...extra,
});

export const GOOD_TOOLS = [
  tool("get_balance", { account: { type: "string" } }, { annotations: { readOnlyHint: true } }),
  tool("create_payment_quote", { amount_kobo: { type: "number" }, idempotency_key: { type: "string" } }),
  tool("approve_quote", { quote_id: { type: "string" }, approval_token: { type: "string" } }, { _meta: { ui: { visibility: ["app"] } } }),
];
export { tool };
