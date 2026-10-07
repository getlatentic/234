// SPDX-License-Identifier: AGPL-3.0-or-later
// Prints a new RSA 2048 private key as one line of JWK with a kid: the host's PACT_SIGNING_KEY
// (host/src/pact/signing.py). tools/deploy.sh stores it as a secret; tools/stack.sh makes one per local stack.
import { generateKeyPairSync, randomUUID } from "node:crypto";

const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
process.stdout.write(JSON.stringify({ ...privateKey.export({ format: "jwk" }), kid: `234-${randomUUID()}` }));
