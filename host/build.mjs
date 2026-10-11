// SPDX-License-Identifier: AGPL-3.0-or-later
// Builds the host's front end: the design tokens, the Tailwind stylesheet and the one vendored file, the AppBridge.
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";
import { buildSync } from "esbuild";

const root = new URL("..", import.meta.url).pathname;
const out = `${root}host/build/`;
mkdirSync(out, { recursive: true });

// A file that is already right is left alone: another local stack may be copying it into its own assets.
function keep(name, text) {
  let current = null;
  try {
    current = readFileSync(`${out}${name}`, "utf8");
  } catch {}
  if (current !== text) writeFileSync(`${out}${name}`, text);
}

execFileSync("node", [`${root}design/build.mjs`], { stdio: "inherit" });
const scratch = mkdtempSync(`${tmpdir()}/host-build-`);
try {
  execFileSync(`${root}node_modules/.bin/tailwindcss`, ["-i", `${root}host/web/app.css`, "-o", `${scratch}/app.css`, "--minify"], {
    cwd: `${root}host`,
    stdio: "inherit",
  });
  keep("app.css", readFileSync(`${scratch}/app.css`, "utf8"));
} finally {
  rmSync(scratch, { recursive: true, force: true });
}

// The official AppBridge as one ES module: the only vendored file the host page loads.
const bridge = buildSync({
  stdin: {
    contents: 'export { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge";',
    resolveDir: root,
  },
  bundle: true,
  minify: true,
  format: "esm",
  write: false,
});
keep("app-bridge.min.js", bridge.outputFiles[0].text);
