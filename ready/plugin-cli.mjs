#!/usr/bin/env node
// SPDX-License-Identifier: AGPL-3.0-or-later
// usage: node ready/plugin-cli.mjs <plugin-dir> [--servers] [--header "Name: value"]... [--json]
// Checks an Agent Plugins 1.0.0 folder; with --servers, also runs 234 MCP Ready on each Streamable HTTP server
// it lists. Exit code 1 when a "must" rule fails.
import { parseArgs } from "node:util";
import { render, verdict } from "./report.mjs";
import { serversOf, validatePlugin } from "./plugin/validate.mjs";
import { runReady } from "./run.mjs";

const { values, positionals } = parseArgs({ allowPositionals: true, options: { servers: { type: "boolean" }, header: { type: "string", multiple: true }, json: { type: "boolean" } } });
const [root] = positionals;
if (!root) {
  console.error('usage: node ready/plugin-cli.mjs <plugin-dir> [--servers] [--header "Name: value"]... [--json]');
  process.exit(2);
}
const headers = Object.fromEntries((values.header ?? []).map((h) => [h.slice(0, h.indexOf(":")).trim(), h.slice(h.indexOf(":") + 1).trim()]));
const results = validatePlugin(root);
if (values.servers && verdict(results).failed === 0) {
  for (const { name, url } of serversOf(root)) {
    const checked = await runReady({ url, headers });
    results.push(...checked.map((r) => ({ ...r, id: `${name}/${r.id}` })));
  }
}
console.log(values.json ? JSON.stringify({ ...verdict(results), results }, null, 2) : render(results));
process.exit(verdict(results).failed ? 1 : 0);
