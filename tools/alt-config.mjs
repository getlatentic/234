// SPDX-License-Identifier: AGPL-3.0-or-later
// Writes host/wrangler.alt.jsonc for the alternative turn runners (TURN_RUNNER=queue or waituntil):
// the host's own config, without its build step (the default host has already built the assets) and with
// the Queue the queue runner needs. The default runner's config stays free of both.
import { readFileSync, writeFileSync } from "node:fs";

const root = new URL("..", import.meta.url).pathname;
const text = readFileSync(`${root}host/wrangler.jsonc`, "utf8");
const config = JSON.parse(text.split("\n").filter((line) => !line.trim().startsWith("//")).join("\n"));
delete config.build;
config.queues = {
  producers: [{ binding: "TURNS", queue: "turns" }],
  consumers: [{ queue: "turns", max_batch_size: 1, max_batch_timeout: 0 }],
};
writeFileSync(`${root}host/wrangler.alt.jsonc`, `${JSON.stringify(config, null, 2)}\n`);
