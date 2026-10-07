// SPDX-License-Identifier: AGPL-3.0-or-later
// What both PACT runs share: PACT 1.0's own repository (openpactprotocol/openpactprotocol, pinned below), cloned
// into .stack/ and installed with its own pnpm; the personal agent the stack registers with PACT=1 (an ES256
// key made here, its JWKS served on PORT_BASE+18, tools/stack.sh pact_vars); and the suite's own client
// library, bundled with esbuild so a plain Node script can use it as the suite does.
import { execFileSync } from "node:child_process";
import { generateKeyPairSync, randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { createServer } from "node:http";
import { buildSync } from "esbuild";

const SUITE = "https://github.com/openpactprotocol/openpactprotocol";
const COMMIT = "838c6bd1da9be39da04264e8b156dbb4e848a208";
export const PNPM = ["--yes", "pnpm@11.21.0"]; // the suite's own packageManager, so nothing beyond npm is needed
export const AUDIENCE = "234-local-pact";
const base = Number(process.env.PORT_BASE ?? 8900);
export const ISSUER = `http://127.0.0.1:${base + 18}`;
export const SUITE_DIR = new URL(`../.stack/pact-suite-${COMMIT.slice(0, 12)}`, import.meta.url).pathname;

export function installSuite() {
  if (!existsSync(`${SUITE_DIR}/e2e/package.json`)) {
    execFileSync("git", ["clone", "-q", SUITE, SUITE_DIR], { stdio: "inherit" });
    execFileSync("git", ["-C", SUITE_DIR, "checkout", "-q", COMMIT], { stdio: "inherit" });
  }
  execFileSync("npx", [...PNPM, "install", "--silent", "--frozen-lockfile", "--filter", "@openpactprotocol/e2e..."], {
    cwd: SUITE_DIR,
    stdio: "inherit",
  });
}

/** The suite's client and its Delegated half, as one ES module. */
export async function suiteClient() {
  const outfile = `${SUITE_DIR}/.bundle/client.mjs`;
  buildSync({
    stdin: {
      contents: 'export * from "./packages/client/src/index.ts"; export * from "./packages/client/src/delegation.ts";',
      resolveDir: SUITE_DIR,
      loader: "ts",
    },
    bundle: true,
    platform: "node",
    format: "esm",
    outfile,
    nodePaths: [`${SUITE_DIR}/packages/client/node_modules`, `${SUITE_DIR}/packages/protocol/node_modules`],
    logLevel: "warning",
  });
  return import(outfile);
}

/** The personal agent: its key, and its JWKS served until `close`. */
export async function personalAgent() {
  const { privateKey, publicKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
  const kid = `pa-${randomUUID()}`;
  const publicJwk = { ...publicKey.export({ format: "jwk" }), kid, alg: "ES256", use: "sig" };
  const privateJwk = { ...privateKey.export({ format: "jwk" }), kid, alg: "ES256" };
  const server = createServer((req, res) => {
    if (req.url !== "/jwks.json") return void res.writeHead(404).end();
    res.writeHead(200, { "content-type": "application/json", "cache-control": "max-age=300" });
    res.end(JSON.stringify({ keys: [publicJwk] }));
  });
  await new Promise((done) => server.listen(base + 18, "127.0.0.1", done));
  return { privateJwk, close: () => server.close() };
}
