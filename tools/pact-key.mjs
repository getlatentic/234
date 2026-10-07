// SPDX-License-Identifier: AGPL-3.0-or-later
// Prints a new private key as one line of JWK with a kid: RSA 2048 for the host's PACT_SIGNING_KEY
// (host/src/pact/signing.py), or with --ec a P-256 key for PACT_AGENT_KEY, 234's own key as a personal agent
// (host/src/turns/reach/), since PACT's reference Provider registers ES256 agents only. tools/deploy.sh stores
// each as a secret; tools/stack.sh makes them per local stack.
import { generateKeyPairSync, randomUUID } from "node:crypto";

const { privateKey } = process.argv.includes("--ec")
  ? generateKeyPairSync("ec", { namedCurve: "P-256" })
  : generateKeyPairSync("rsa", { modulusLength: 2048 });
process.stdout.write(JSON.stringify({ ...privateKey.export({ format: "jwk" }), kid: `234-${randomUUID()}` }));
