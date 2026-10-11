// SPDX-License-Identifier: AGPL-3.0-or-later
// usage: node tools/host-config.mjs <port base> <connectors Worker name>
// Writes the host's configs for one local stack, as production wires it: the connectors reached through the
// CHECKOUT_MCP service binding (wrangler's dev registry), never over localhost, whose dev server drops a
// keep-alive connection at the moment it is reused after five idle seconds. The connectors Worker of each
// stack has its own name, so two stacks never reach each other's, and each stack serves its own assets folder.
//   host/wrangler.stack-<base>.jsonc      the default turn runner: the host's own config and its build step
//   host/wrangler.stack-<base>.alt.jsonc  the queue and waitUntil runners: no build step (the default host has
//                                         built the assets already), and the Queue the queue runner needs
import { readFileSync, writeFileSync } from "node:fs";

const [base, connectors] = process.argv.slice(2);
if (!base || !connectors) throw new Error("usage: host-config.mjs <port base> <connectors Worker name>");
const root = new URL("..", import.meta.url).pathname;
const text = readFileSync(`${root}host/wrangler.jsonc`, "utf8");
const config = JSON.parse(text.split("\n").filter((line) => !line.trim().startsWith("//")).join("\n"));
config.services = [{ binding: "CHECKOUT_MCP", service: connectors }];
// Its own assets folder, which tools/stack.sh's build_shell also fills: starting another stack never empties it.
const assets = `${root}.stack/${base}/assets`;
config.assets = { ...config.assets, directory: assets };
config.build = { ...config.build, command: `export HOST_ASSETS_DIR=${assets} && ${config.build.command}` };
config.vars = { ...config.vars, CHECKOUT_MCP_BINDING: "CHECKOUT_MCP" };
const write = (name, value) => writeFileSync(`${root}host/${name}`, `${JSON.stringify(value, null, 2)}\n`);
write(`wrangler.stack-${base}.jsonc`, config);

const { build, ...alt } = config;
alt.queues = {
  producers: [{ binding: "TURNS", queue: "turns" }],
  consumers: [{ queue: "turns", max_batch_size: 1, max_batch_timeout: 0 }],
};
write(`wrangler.stack-${base}.alt.jsonc`, alt);
