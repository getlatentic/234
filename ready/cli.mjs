#!/usr/bin/env node
// SPDX-License-Identifier: AGPL-3.0-or-later
// usage: node ready/cli.mjs <mcp-url> [--header "Name: value"]... [--fixture calls.json] [--json]
// Checks a remote MCP server against the rules a 234 host relies on. Exit code 1 when a "must" rule fails.
import { readFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { render, verdict } from "./report.mjs";
import { runReady } from "./run.mjs";

const { values, positionals } = parseArgs({ allowPositionals: true, options: { header: { type: "string", multiple: true }, fixture: { type: "string" }, json: { type: "boolean" } } });
const [url] = positionals;
if (!url) {
  console.error('usage: node ready/cli.mjs <mcp-url> [--header "Name: value"]... [--fixture calls.json] [--json]');
  process.exit(2);
}
const headers = Object.fromEntries((values.header ?? []).map((h) => [h.slice(0, h.indexOf(":")).trim(), h.slice(h.indexOf(":") + 1).trim()]));
const calls = values.fixture ? JSON.parse(readFileSync(values.fixture, "utf8")).calls : [];
const results = await runReady({ url, headers, calls });
console.log(values.json ? JSON.stringify({ ...verdict(results), results }, null, 2) : render(results));
process.exit(verdict(results).failed ? 1 : 0);
