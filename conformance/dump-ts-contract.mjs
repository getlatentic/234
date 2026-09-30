// SPDX-License-Identifier: AGPL-3.0-or-later
// Prints tools/list and resources/list of the TypeScript demo's connector (a copy of its built dist/ under a
// directory with no .env, ledger in /tmp), for comparing the contract with the Python server's.
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";

const [dir, bin] = process.argv.slice(2);
const client = new Client({ name: "contract-dump", version: "0.1.0" });
await client.connect(new StdioClientTransport({
  command: process.execPath, args: [`${dir}/dist/connectors/${bin}/bin.js`], cwd: dir,
  env: { PATH: process.env.PATH, LEDGER_PATH: `${dir}/ledger.sqlite`, PAYSTACK_MODE: "simulated", VTPASS_MODE: "simulated" },
}));
const out = {
  server: client.getServerVersion(), capabilities: client.getServerCapabilities(),
  tools: (await client.listTools()).tools, resources: (await client.listResources()).resources,
};
const uri = out.resources.find((r) => r.uri.startsWith("ui://")).uri;
const card = (await client.readResource({ uri })).contents[0];
out.card = { uri: card.uri, mimeType: card.mimeType, _meta: card._meta, bytes: card.text.length };
console.log(JSON.stringify(out, null, 1));
await client.close();
