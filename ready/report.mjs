// SPDX-License-Identifier: AGPL-3.0-or-later
const MARK = { must: "FAIL", should: "WARN", skip: "SKIP" };

export const verdict = (results) => ({
  failed: results.filter((r) => !r.ok && r.level === "must").length,
  warned: results.filter((r) => !r.ok && r.level === "should").length,
  passed: results.filter((r) => r.ok && r.level !== "skip").length,
});

export function render(results) {
  const lines = results.map((r) => `  ${r.ok ? (r.level === "skip" ? "SKIP" : "PASS") : MARK[r.level]}  ${r.id}  ${r.detail}`);
  const { failed, warned, passed } = verdict(results);
  return [...lines, "", `${passed} passed, ${warned} warnings, ${failed} failed: ${failed ? "not 234 MCP Ready" : "234 MCP Ready"}`].join("\n");
}
