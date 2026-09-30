// SPDX-License-Identifier: AGPL-3.0-or-later
// The Content-Security-Policy of a view, built from the origins its resource declares (`_meta.ui.csp`).
// The host validates a declaration before it sends it; this module validates it again, because the policy
// is the last thing between a view and the network and a compromised host page must not widen it.

export const FIELDS = ["connectDomains", "resourceDomains", "frameDomains", "baseUriDomains"];
export const MAX_ENTRIES = 16;

const LABEL = "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?";
const PORT = "(?::[1-9][0-9]{0,4})?";
const HOSTNAME = `(?:${LABEL}\\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?`;
const SCHEMES = { connectDomains: ["https", "wss"] };
const SOURCE = (schemes) => new RegExp(`^(?:${schemes.join("|")})://(?:\\*\\.)?${HOSTNAME}${PORT}$`);
const SOURCES = Object.fromEntries(FIELDS.map((field) => [field, SOURCE(SCHEMES[field] ?? ["https"])]));

/** Why an entry is not taken, or null when it is a source a server may declare. */
export function refusal(field, entry) {
  if (typeof entry !== "string") return "not a string";
  if (entry.length > 300) return "too long";
  const matched = SOURCES[field].test(entry);
  if (!matched) return "not an https origin (wss for connections), with an optional *. subdomain and port";
  const port = entry.match(/:([0-9]+)$/);
  if (port && Number(port[1]) > 65535) return "port out of range";
  return null;
}

/**
 * The entries of a declaration that may be used, and the ones that are refused with the reason.
 * `declared` is untrusted: anything that is not an object of arrays of strings yields nothing.
 */
export function sanitize(declared) {
  const csp = {};
  const refused = [];
  const source = declared !== null && typeof declared === "object" && !Array.isArray(declared) ? declared : {};
  for (const field of FIELDS) {
    const list = source[field];
    if (list === undefined) continue;
    if (!Array.isArray(list)) {
      refused.push({ field, entry: String(list).slice(0, 80), reason: "not a list" });
      continue;
    }
    const kept = [];
    for (const entry of list) {
      const reason = kept.length >= MAX_ENTRIES ? `more than ${MAX_ENTRIES} entries` : refusal(field, entry);
      if (reason) refused.push({ field, entry: String(entry).slice(0, 80), reason });
      else if (!kept.includes(entry)) kept.push(entry);
    }
    if (kept.length) csp[field] = kept;
  }
  return { csp, refused };
}

/** What the host signs: the embedder and the sanitized declaration, one field a line in a fixed order. */
export const canonical = (host, csp) =>
  [host, ...FIELDS.filter((field) => csp[field]?.length).map((field) => `${field}=${csp[field].join(",")}`)].join("\n");

const bytes = (hex) => Uint8Array.from(hex.match(/../g) ?? [], (pair) => Number.parseInt(pair, 16));

/** Whether `given` (hex) is the HMAC-SHA256 of the canonical text under `secret`: the host's word that it issued this policy. */
export async function isSigned(secret, host, csp, given) {
  if (typeof given !== "string" || !/^[0-9a-f]{64}$/.test(given)) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  return crypto.subtle.verify("HMAC", key, bytes(given), new TextEncoder().encode(canonical(host, csp)));
}

const join = (...sources) => sources.filter(Boolean).join(" ");

/** The policy of ext-apps specification 2026-01-26, "Security Implications", one directive per line of it. */
export function buildPolicy(csp, ancestors) {
  const resources = (csp.resourceDomains ?? []).join(" ");
  const connect = (csp.connectDomains ?? []).join(" ");
  const frames = (csp.frameDomains ?? []).join(" ");
  const bases = (csp.baseUriDomains ?? []).join(" ");
  return [
    "default-src 'none'",
    join("script-src 'self' 'unsafe-inline'", resources),
    join("style-src 'self' 'unsafe-inline'", resources),
    join("connect-src 'self'", connect),
    join("img-src 'self' data:", resources),
    join("font-src 'self'", resources),
    join("media-src 'self' data:", resources),
    `frame-src ${frames || "'none'"}`,
    "object-src 'none'",
    `base-uri ${bases || "'self'"}`,
    "form-action 'none'",
    join("frame-ancestors", ancestors),
  ].join("; ");
}
