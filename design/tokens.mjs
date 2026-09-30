// SPDX-License-Identifier: AGPL-3.0-or-later
// tokens.json with its aliases resolved: a theme colour written "brand.deep" is the brand palette colour of that name.
import { readFileSync } from "node:fs";

const PATH = new URL("./tokens.json", import.meta.url);

export function loadTokens() {
  const tokens = JSON.parse(readFileSync(PATH, "utf8"));
  const resolve = (value) => {
    if (!value.startsWith("brand.")) return value;
    const found = tokens.brand[value.slice("brand.".length)];
    if (found === undefined) throw new Error(`tokens.json: no brand colour ${value}`);
    return found;
  };
  for (const theme of Object.keys(tokens.colors)) {
    tokens.colors[theme] = Object.fromEntries(Object.entries(tokens.colors[theme]).map(([name, value]) => [name, resolve(value)]));
  }
  return tokens;
}
