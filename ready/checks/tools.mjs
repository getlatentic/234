// SPDX-License-Identifier: AGPL-3.0-or-later
import { must, should } from "../result.mjs";
import { isModelVisible, isReadOnly } from "../tools-model.mjs";

const NAME = /^[a-z][a-z0-9_]{0,63}$/;
const MODEL_TOOL_BUDGET = 25;
const names = (tools) => tools.map((t) => t.name).join(", ") || "none";

export function toolSurface({ tools }) {
  const duplicates = tools.filter((t, i) => tools.findIndex((o) => o.name === t.name) !== i);
  const badNames = tools.filter((t) => !NAME.test(t.name));
  const thin = tools.filter((t) => (t.description ?? "").trim().length < 20);
  const noSchema = tools.filter((t) => t.inputSchema?.type !== "object");
  const noReadHint = tools.filter((t) => typeof t.annotations?.readOnlyHint !== "boolean");
  const writes = tools.filter((t) => !isReadOnly(t));
  const noWriteHints = writes.filter((t) => typeof t.annotations?.destructiveHint !== "boolean" || typeof t.annotations?.idempotentHint !== "boolean");
  const visible = tools.filter(isModelVisible);
  return [
    must("tools.listed", tools.length > 0, `${tools.length} tools`),
    must("tools.unique-names", duplicates.length === 0, duplicates.length ? `repeated: ${names(duplicates)}` : "every name is unique"),
    should("tools.snake-case-names", badNames.length === 0, badNames.length ? `rename: ${names(badNames)}` : "names are lower snake_case"),
    must("tools.descriptions", thin.length === 0, thin.length ? `describe what these do and when to use them: ${names(thin)}` : "every tool is described"),
    must("tools.input-schema", noSchema.length === 0, noSchema.length ? `inputSchema must be an object: ${names(noSchema)}` : "every tool has an object inputSchema"),
    must("tools.read-only-hint", noReadHint.length === 0, noReadHint.length ? `set readOnlyHint: ${names(noReadHint)}` : "every tool says whether it only reads"),
    must("tools.write-hints", noWriteHints.length === 0, noWriteHints.length ? `set destructiveHint and idempotentHint: ${names(noWriteHints)}` : "every write tool says whether it destroys and whether it repeats safely"),
    should("tools.model-budget", visible.length <= MODEL_TOOL_BUDGET, `${visible.length} tools offered to the model (keep it at ${MODEL_TOOL_BUDGET} or fewer)`),
  ];
}
