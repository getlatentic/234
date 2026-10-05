// SPDX-License-Identifier: AGPL-3.0-or-later
import { must, skipped } from "../result.mjs";
import { isReadOnly, propertyNames } from "../tools-model.mjs";

async function refused(client, params) {
  try {
    const result = await client.callTool(params);
    return result.isError === true;
  } catch {
    return true;
  }
}

export async function errorBehaviour({ client, tools }) {
  const unknown = await refused(client, { name: "no_such_tool_0f3a", arguments: {} });
  const needy = tools.find((t) => (t.inputSchema?.required ?? []).length > 0 && propertyNames(t).length > 0);
  const results = [must("errors.unknown-tool", unknown, "an unknown tool is refused")];
  if (!needy) return [...results, skipped("errors.missing-arguments", "no tool has required arguments")];
  const rejected = await refused(client, { name: needy.name, arguments: {} });
  return [...results, must("errors.missing-arguments", rejected, `${needy.name} refuses a call without its required arguments${isReadOnly(needy) ? "" : " (no side effect ran)"}`)];
}
