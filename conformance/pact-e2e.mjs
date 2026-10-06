// SPDX-License-Identifier: AGPL-3.0-or-later
// PACT 1.0's own conformance suite (openpactprotocol/openpactprotocol, e2e/, pinned below), run against this
// host as a Provider: the Identity profile's discovery, contexts, retries, isolation across Users and Brands,
// task routes, error envelopes, content types, unmatched routes and every authentication negative. The
// personal agent it signs as is made here: an ES256 key whose JWKS this script serves on PORT_BASE+18, the
// issuer the stack registers when started with PACT=1 (tools/stack.sh pact_vars).
// usage: PACT=1 tools/up.sh, then PORT_BASE=… node conformance/pact-e2e.mjs (it clones the suite into .stack/)
import { execFileSync, spawn } from "node:child_process";
import { generateKeyPairSync, randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { createServer } from "node:http";
import { HOST } from "./lib.mjs";

const SUITE = "https://github.com/openpactprotocol/openpactprotocol";
const PNPM = ["--yes", "pnpm@11.21.0"]; // the suite's own packageManager, so nothing beyond npm is needed
const COMMIT = "838c6bd1da9be39da04264e8b156dbb4e848a208";
const base = Number(process.env.PORT_BASE ?? 8900);
const issuer = `http://127.0.0.1:${base + 18}`;
const dir = new URL(`../.stack/pact-suite-${COMMIT.slice(0, 12)}`, import.meta.url).pathname;

if (!existsSync(`${dir}/e2e/package.json`)) {
  execFileSync("git", ["clone", "-q", SUITE, dir], { stdio: "inherit" });
  execFileSync("git", ["-C", dir, "checkout", "-q", COMMIT], { stdio: "inherit" });
}
execFileSync("npx", [...PNPM, "install", "--silent", "--frozen-lockfile", "--filter", "@openpactprotocol/e2e..."], { cwd: dir, stdio: "inherit" });

const { privateKey, publicKey } = generateKeyPairSync("ec", { namedCurve: "P-256" });
const kid = `pa-${randomUUID()}`;
const publicJwk = { ...publicKey.export({ format: "jwk" }), kid, alg: "ES256", use: "sig" };
const privateJwk = { ...privateKey.export({ format: "jwk" }), kid, alg: "ES256" };
const jwks = createServer((req, res) => {
  if (req.url !== "/jwks.json") return void res.writeHead(404).end();
  res.writeHead(200, { "content-type": "application/json", "cache-control": "max-age=300" });
  res.end(JSON.stringify({ keys: [publicJwk] }));
});
await new Promise((done) => jwks.listen(base + 18, "127.0.0.1", done));

// spawn, not spawnSync: the JWKS above must keep answering while the suite runs.
const run = spawn("npx", [...PNPM, "e2e"], {
  cwd: dir,
  stdio: "inherit",
  env: {
    ...process.env,
    PROVIDER_URL: HOST,
    CUSTOMER_ID: "234",
    OTHER_CUSTOMER_ID: "food",
    PA_ISSUER: issuer,
    PA_AUDIENCE: "234-local-pact",
    PA_PRIVATE_JWK: JSON.stringify(privateJwk),
    E2E_PROVIDER: "any",
    E2E_TEST_TIMEOUT_MS: "90000",
  },
});
const status = await new Promise((done) => run.on("close", done));
jwks.close();
process.exit(status ?? 1);
