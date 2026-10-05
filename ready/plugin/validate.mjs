// SPDX-License-Identifier: AGPL-3.0-or-later
// A plugin folder against Agent Plugins 1.0.0: the manifest, the MCP configuration, the skills, and that no
// path of the package resolves outside it.
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { must } from "../result.mjs";
import { manifestRules, mcpRules } from "./manifest.mjs";
import { skillDirs, skillRules } from "./skills.mjs";

function readJson(path) {
  try {
    return { document: JSON.parse(readFileSync(path, "utf8")) };
  } catch (error) {
    return { problem: error.message };
  }
}

function contained(root, path) {
  const inside = relative(realpathSync(root), realpathSync(path));
  return !inside.startsWith(`..${sep}`) && inside !== "..";
}

export function validatePlugin(root) {
  const manifestPath = join(root, "plugin.json");
  if (!existsSync(manifestPath)) return [must("plugin.manifest", false, "there is no plugin.json at the plugin root")];
  const { document: manifest, problem } = readJson(manifestPath);
  if (problem) return [must("plugin.manifest", false, `plugin.json is not JSON: ${problem}`)];
  const results = manifestRules(manifest);
  const mcpPath = join(root, "mcp.json");
  if (existsSync(mcpPath)) {
    const mcp = readJson(mcpPath);
    results.push(...(mcp.problem ? [must("mcp.schema", false, `mcp.json is not JSON: ${mcp.problem}`)] : mcpRules(mcp.document, manifest)));
  }
  results.push(...skillRules(root));
  const skills = skillDirs(root).flatMap((name) => [join(root, "skills", name), join(root, "skills", name, "SKILL.md")]);
  const paths = [manifestPath, mcpPath, join(root, "skills"), ...skills].filter(existsSync);
  const outside = paths.filter((p) => !contained(root, p));
  results.push(must("plugin.contained", outside.length === 0, outside.length ? `resolve outside the plugin: ${outside.join(", ")}` : "every package path stays inside the plugin"));
  return results;
}

/** The streamable-http servers of a valid plugin, for the MCP Ready checks. */
export function serversOf(root) {
  const path = join(root, "mcp.json");
  if (!existsSync(path)) return [];
  const { document } = readJson(path);
  return Object.entries(document?.mcpServers ?? {}).filter(([, s]) => s.type === "streamable-http").map(([name, s]) => ({ name, url: s.url }));
}
