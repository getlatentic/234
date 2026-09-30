// SPDX-License-Identifier: AGPL-3.0-or-later
// Builds the host's front end: the design tokens, the Tailwind stylesheet and the one vendored file, the AppBridge.
import { mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { buildSync } from "esbuild";

const root = new URL("..", import.meta.url).pathname;
const out = `${root}host/build/`;
mkdirSync(out, { recursive: true });
execFileSync("node", [`${root}design/build.mjs`], { stdio: "inherit" });
execFileSync(`${root}node_modules/.bin/tailwindcss`, ["-i", `${root}host/web/app.css`, "-o", `${out}app.css`, "--minify"], {
  cwd: `${root}host`,
  stdio: "inherit",
});

// The official AppBridge as one ES module: the only vendored file the host page loads.
buildSync({
  stdin: {
    contents: 'export { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge";',
    resolveDir: root,
  },
  bundle: true,
  minify: true,
  format: "esm",
  outfile: `${out}app-bridge.min.js`,
});
