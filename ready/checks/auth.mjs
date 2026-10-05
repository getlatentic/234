// SPDX-License-Identifier: AGPL-3.0-or-later
import { must, should } from "../result.mjs";

const INIT = { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "234-ready", version: "0.1.0" } } };

// Always asked without credentials: a server given a token must still challenge a caller that has none.
export async function authentication({ url }) {
  const response = await fetch(url, { method: "POST", headers: { "content-type": "application/json", accept: "application/json, text/event-stream" }, body: JSON.stringify(INIT) });
  await response.body?.cancel();
  if (response.status !== 401) return [should("auth.challenge", false, `the server answers without sign-in (HTTP ${response.status}); a server that acts for a person must require OAuth`)];
  const challenge = response.headers.get("www-authenticate") ?? "";
  const metadataUrl = /resource_metadata="([^"]+)"/.exec(challenge)?.[1] ?? new URL("/.well-known/oauth-protected-resource", url).href;
  const metadata = await fetch(metadataUrl).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  return [
    must("auth.challenge", /^Bearer/i.test(challenge), "401 carries a Bearer challenge"),
    must("auth.protected-resource", Array.isArray(metadata?.authorization_servers) && metadata.authorization_servers.length > 0, `protected-resource metadata names an authorization server (${metadataUrl})`),
    should("auth.scopes", Array.isArray(metadata?.scopes_supported) && metadata.scopes_supported.length > 0, "the metadata lists the scopes it uses"),
  ];
}
