// SPDX-License-Identifier: AGPL-3.0-or-later
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { validatePlugin } from "./plugin/validate.mjs";

const PLUGIN = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json";
const MCP = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json";
const SKILL = "---\nname: pay\ndescription: Pays for things when a person asks.\n---\n\n# Pay\n";

function plugin({ manifest = { $schema: PLUGIN, name: "acme.pay", version: "1.0.0" }, mcp, skills = { pay: SKILL } } = {}) {
  const root = mkdtempSync(join(tmpdir(), "plugin-"));
  writeFileSync(join(root, "plugin.json"), typeof manifest === "string" ? manifest : JSON.stringify(manifest));
  if (mcp) writeFileSync(join(root, "mcp.json"), JSON.stringify(mcp));
  for (const [name, body] of Object.entries(skills)) {
    mkdirSync(join(root, "skills", name), { recursive: true });
    writeFileSync(join(root, "skills", name, "SKILL.md"), body);
  }
  return root;
}
const server = (extra = {}) => ({ $schema: MCP, mcpServers: { pay: { type: "streamable-http", url: "https://pay.example/mcp", ...extra } } });
const failing = (root) => validatePlugin(root).filter((r) => !r.ok && r.level === "must").map((r) => r.id);

test("a plugin with a manifest, an MCP server and a skill passes", () => {
  assert.deepEqual(failing(plugin({ mcp: server() })), []);
});

test("the repository's own 234 plugin passes", () => {
  assert.deepEqual(failing(new URL("../plugins/234", import.meta.url).pathname), []);
});

test("a manifest with an uppercase name, an unknown field or no $schema fails", () => {
  for (const manifest of [{ $schema: PLUGIN, name: "Acme" }, { $schema: PLUGIN, name: "acme", mcpServers: {} }, { name: "acme" }, "{not json"]) {
    assert.deepEqual(failing(plugin({ manifest })), ["plugin.manifest"], JSON.stringify(manifest));
  }
});

test("an HTTP URL off localhost, user information or a fragment fails", () => {
  for (const url of ["http://pay.example/mcp", "https://me@pay.example/mcp", "https://pay.example/mcp#x"]) {
    assert.deepEqual(failing(plugin({ mcp: server({ url }) })), ["mcp.servers"], url);
  }
  assert.deepEqual(failing(plugin({ mcp: server({ url: "http://localhost:8787/mcp" }) })), []);
});

test("a credential in package data fails", () => {
  assert.deepEqual(failing(plugin({ mcp: server({ headers: { Authorization: "Bearer abc" } }) })), ["mcp.servers"]);
  const stdio = { $schema: MCP, mcpServers: { pay: { type: "stdio", command: "pay-server", env: { PAY_API_KEY: "sk" } } } };
  assert.deepEqual(failing(plugin({ mcp: stdio })), ["mcp.servers"]);
});

test("a stdio command that is a shell line fails", () => {
  const stdio = { $schema: MCP, mcpServers: { pay: { type: "stdio", command: "node server.js" } } };
  assert.deepEqual(failing(plugin({ mcp: stdio })), ["mcp.servers"]);
});

test("an mcp.json that breaks its schema or targets another version fails", () => {
  assert.deepEqual(failing(plugin({ mcp: { $schema: MCP, mcpServers: { pay: { url: "https://pay.example/mcp" } } } })), ["mcp.schema"]);
  assert.deepEqual(failing(plugin({ mcp: { ...server(), $schema: "https://agent-plugins.org/schemas/2.0.0/mcp.schema.json" } })), ["mcp.schema"]);
});

test("a skill whose name is not its directory, or has no description, fails", () => {
  assert.deepEqual(failing(plugin({ skills: { pay: SKILL.replace("name: pay", "name: payer") } })), ["skills"]);
  assert.deepEqual(failing(plugin({ skills: { pay: "---\nname: pay\n---\n" } })), ["skills"]);
  assert.deepEqual(failing(plugin({ skills: { pay: "# no front matter" } })), ["skills"]);
});

test("a skill that is a link to a folder outside the plugin fails", () => {
  const outside = mkdtempSync(join(tmpdir(), "outside-"));
  writeFileSync(join(outside, "SKILL.md"), SKILL.replace("name: pay", "name: away"));
  const root = plugin();
  symlinkSync(outside, join(root, "skills", "away"));
  assert.deepEqual(failing(root), ["plugin.contained"]);
});
