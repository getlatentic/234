// SPDX-License-Identifier: AGPL-3.0-or-later
// plugin.json and mcp.json against the official Agent Plugins 1.0.0 JSON Schemas (copied into schemas/ from
// https://agent-plugins.org/schemas/1.0.0/), plus the rules of the specification a schema cannot state.
import { readFileSync } from "node:fs";
import Ajv2020 from "ajv/dist/2020.js";
import { must, should } from "../result.mjs";

const ajv = new Ajv2020({ allErrors: true, strict: false });
const schema = (name) => JSON.parse(readFileSync(new URL(`./schemas/${name}.schema.json`, import.meta.url), "utf8"));
const validators = { plugin: ajv.compile(schema("plugin")), mcp: ajv.compile(schema("mcp")) };
const SEMVER = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;
const SECRET_NAME = /authorization|token|secret|password|api[-_]?key|cookie/i;

const problems = (validate) => (validate.errors ?? []).map((e) => `${e.instancePath || "/"} ${e.message}`).join("; ");
const versionOf = (document) => /\/schemas\/([^/]+)\//.exec(document?.$schema ?? "")?.[1];

export function manifestRules(manifest) {
  const valid = validators.plugin(manifest);
  return [
    must("plugin.manifest", valid, valid ? `plugin.json names ${manifest.name}` : `plugin.json: ${problems(validators.plugin)}`),
    should("plugin.version", SEMVER.test(manifest?.version ?? ""), `version is semantic (${manifest?.version ?? "none"})`),
  ];
}

function urlProblem(raw) {
  let url;
  try {
    url = new URL(raw);
  } catch {
    return "is not an absolute URL";
  }
  if (!["http:", "https:"].includes(url.protocol)) return "is not HTTP or HTTPS";
  if (url.username || url.password || url.hash) return "carries user information or a fragment";
  if (url.protocol === "http:" && url.hostname !== "localhost") return "uses HTTP on a host other than localhost";
  return null;
}

const commandOk = (command) => !/\s/.test(command) && (!command.includes("/") || command.startsWith("./"));

function serverProblems(name, server) {
  const found = [];
  if (server.url) {
    const problem = urlProblem(server.url);
    if (problem) found.push(`${name}: url ${problem}`);
  }
  for (const header of Object.keys(server.headers ?? {})) {
    if (SECRET_NAME.test(header)) found.push(`${name}: header ${header} would carry a credential in package data`);
  }
  for (const variable of Object.keys(server.env ?? {})) {
    if (SECRET_NAME.test(variable)) found.push(`${name}: env ${variable} would carry a credential in package data`);
  }
  if (server.type === "stdio" && !commandOk(server.command)) {
    found.push(`${name}: command must be one bare executable name or a ./ path`);
  }
  return found;
}

export function mcpRules(mcp, manifest) {
  const valid = validators.mcp(mcp);
  if (!valid) return [must("mcp.schema", false, `mcp.json: ${problems(validators.mcp)}`)];
  const servers = Object.entries(mcp.mcpServers);
  const found = servers.flatMap(([name, server]) => serverProblems(name, server));
  return [
    must("mcp.schema", true, `mcp.json lists ${servers.length} servers`),
    must("mcp.version", versionOf(mcp) === versionOf(manifest), `mcp.json targets the version plugin.json does (${versionOf(mcp)})`),
    must("mcp.servers", found.length === 0, found.length ? found.join("; ") : "every URL is HTTPS (or localhost) and nothing carries a credential"),
  ];
}
