// SPDX-License-Identifier: AGPL-3.0-or-later
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import { authentication } from "./checks/auth.mjs";
import { errorBehaviour } from "./checks/errors.mjs";
import { handshake } from "./checks/handshake.mjs";
import { moneyRules } from "./checks/money.mjs";
import { idempotentReplay } from "./checks/replay.mjs";
import { toolSurface } from "./checks/tools.mjs";
import { must } from "./result.mjs";

const CHECKS = [handshake, toolSurface, moneyRules, errorBehaviour, authentication, idempotentReplay];

async function connect(url, headers) {
  const client = new Client({ name: "234-ready", version: "0.1.0" });
  await client.connect(new StreamableHTTPClientTransport(new URL(url), { requestInit: { headers } }));
  return client;
}

export async function runReady({ url, headers = {}, calls = [] }) {
  const results = [];
  const unauthenticated = await authentication({ url }).catch((e) => [must("auth.challenge", false, `could not probe sign-in: ${e.message}`)]);
  let client;
  try {
    client = await connect(url, headers);
  } catch (error) {
    return [...unauthenticated, must("connect", false, `could not connect over Streamable HTTP: ${error.message}`)];
  }
  const { tools } = await client.listTools();
  const context = { url, client, tools, calls };
  for (const check of CHECKS.filter((c) => c !== authentication)) results.push(...(await check(context)));
  await client.close();
  return [...results, ...unauthenticated];
}
