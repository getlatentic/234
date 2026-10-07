// SPDX-License-Identifier: AGPL-3.0-or-later
// PACT 1.0's own conformance suite (e2e/ of the pinned repository, conformance/pact-suite.mjs), run against this
// host as a Provider: the Identity profile's discovery, contexts, retries, isolation across Users and Brands,
// task routes, error envelopes, content types, unmatched routes and every authentication negative. The suite's
// Delegated test is written for its reference Brand; 234's is conformance/pact-delegated.mjs.
// usage: PACT=1 tools/up.sh, then PORT_BASE=… node conformance/pact-e2e.mjs (it clones the suite into .stack/)
import { spawn } from "node:child_process";
import { HOST } from "./lib.mjs";
import { AUDIENCE, ISSUER, PNPM, SUITE_DIR, installSuite, personalAgent } from "./pact-suite.mjs";

installSuite();
const agent = await personalAgent();
// spawn, not spawnSync: the agent's JWKS must keep answering while the suite runs.
const run = spawn("npx", [...PNPM, "e2e"], {
  cwd: SUITE_DIR,
  stdio: "inherit",
  env: {
    ...process.env,
    PROVIDER_URL: HOST,
    CUSTOMER_ID: "234",
    OTHER_CUSTOMER_ID: "food",
    PA_ISSUER: ISSUER,
    PA_AUDIENCE: AUDIENCE,
    PA_PRIVATE_JWK: JSON.stringify(agent.privateJwk),
    E2E_PROVIDER: "any",
    E2E_TEST_TIMEOUT_MS: "90000",
  },
});
const status = await new Promise((done) => run.on("close", done));
agent.close();
process.exit(status ?? 1);
