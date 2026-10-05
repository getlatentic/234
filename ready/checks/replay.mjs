// SPDX-License-Identifier: AGPL-3.0-or-later
import { must, skipped } from "../result.mjs";

const outcome = (result) => JSON.stringify(result.structuredContent ?? result.content);

export async function idempotentReplay({ client, calls }) {
  if (!calls?.length) return [skipped("replay.idempotency", "give --fixture with sample calls to check that a repeated idempotency key repeats the result")];
  const results = [];
  for (const { tool, args } of calls) {
    const first = await client.callTool({ name: tool, arguments: args });
    const second = await client.callTool({ name: tool, arguments: args });
    results.push(must(`replay.${tool}`, first.isError !== true && outcome(first) === outcome(second), `${tool} called twice with the same key gives the same result`));
  }
  return results;
}
