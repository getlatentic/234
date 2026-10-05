// SPDX-License-Identifier: AGPL-3.0-or-later
// Each immediate child of skills/ that holds a SKILL.md is one skill, held to the Agent Skills specification:
// YAML front matter with a name equal to its directory and a description of at most 1024 characters.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { parse } from "yaml";
import { must, skipped } from "../result.mjs";

const NAME = /^(?!.*--)[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/;
const FRONT_MATTER = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/;

function skillProblem(dir, name) {
  const found = FRONT_MATTER.exec(readFileSync(join(dir, name, "SKILL.md"), "utf8"));
  if (!found) return `${name}: SKILL.md has no front matter`;
  let meta;
  try {
    meta = parse(found[1]);
  } catch (error) {
    return `${name}: front matter is not YAML (${error.message.split("\n")[0]})`;
  }
  if (meta?.name !== name || !NAME.test(name)) return `${name}: name must be ${name}, lowercase letters, digits and single hyphens`;
  const description = meta.description;
  if (typeof description !== "string" || !description.trim() || description.length > 1024) return `${name}: description must be 1 to 1024 characters`;
  return null;
}

function isSkill(dir, name) {
  try {
    return statSync(join(dir, name)).isDirectory() && statSync(join(dir, name, "SKILL.md")).isFile();
  } catch {
    return false;
  }
}

export const skillDirs = (root) => {
  const dir = join(root, "skills");
  return existsSync(dir) ? readdirSync(dir).filter((name) => isSkill(dir, name)) : [];
};

export function skillRules(root) {
  const dir = join(root, "skills");
  if (!existsSync(dir)) return [skipped("skills", "no skills/ directory")];
  const skills = skillDirs(root);
  const found = skills.map((name) => skillProblem(dir, name)).filter(Boolean);
  return [must("skills", skills.length > 0 && found.length === 0, found.length ? found.join("; ") : `${skills.length} skills: ${skills.join(", ") || "none"}`)];
}
