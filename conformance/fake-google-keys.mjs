// SPDX-License-Identifier: AGPL-3.0-or-later
// A stand-in for Google's key document, for the local stack only (tools/up.sh with AUTH=1): it makes an RSA key
// pair, keeps the private half in <dir>/private.pem for the suites that sign ID tokens, and serves the public half
// as the JSON Web Key set Google publishes, with a Cache-Control the host must honour. The host reads its URL from
// FIREBASE_KEYS_URL, which settings refuse outside development.
// usage: node conformance/fake-google-keys.mjs <port> <dir>
import { generateKeyPairSync } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";

const [port, dir] = [Number(process.argv[2]), process.argv[3]];
const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const kid = `local-${Date.now().toString(36)}`;
mkdirSync(dir, { recursive: true });
writeFileSync(`${dir}/private.pem`, privateKey.export({ type: "pkcs8", format: "pem" }));
writeFileSync(`${dir}/kid`, kid);
const keys = { keys: [{ ...publicKey.export({ format: "jwk" }), kid, use: "sig", alg: "RS256" }] };
let served = 0;

createServer((request, response) => {
  if (request.url === "/served") return response.end(String(served));
  served += 1;
  response.writeHead(200, { "content-type": "application/json", "cache-control": "public, max-age=3600" });
  response.end(JSON.stringify(keys));
}).listen(port, "127.0.0.1");
