// SPDX-License-Identifier: AGPL-3.0-or-later
// The sandbox origin of the card frames (ext-apps specification 2026-01-26, "Sandbox proxy"). It serves three
// static things and holds no state and no cookie: the proxy page, the page a view is written into, and /health.
// Its one secret is the key with which the host signs the policy of a view, so a view cannot ask for a wider one. It is a different origin from the chat host, on its own hostname.
import { buildPolicy, isSigned, sanitize } from "./csp.js";
import { PROXY_SCRIPT, PROXY_STYLE, proxyPage, viewPage } from "./pages.js";

const SECURITY_HEADERS = {
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
};

const sha256 = async (text) => {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));
  return `'sha256-${btoa(String.fromCharCode(...digest))}'`;
};

let proxyPolicy;
const ownPolicy = (ancestors) => {
  proxyPolicy ??= Promise.all([sha256(PROXY_SCRIPT), sha256(PROXY_STYLE)]);
  return proxyPolicy.then(([script, style]) =>
    [
      "default-src 'none'",
      `script-src ${script}`,
      `style-src ${style}`,
      "frame-src 'self'",
      "base-uri 'none'",
      "form-action 'none'",
      `frame-ancestors ${ancestors}`,
    ].join("; "),
  );
};

const html = (body, policy) =>
  new Response(body, { headers: { ...SECURITY_HEADERS, "content-type": "text/html; charset=utf-8", "content-security-policy": policy } });

const plain = (status, text) =>
  new Response(text, { status, headers: { ...SECURITY_HEADERS, "content-type": "text/plain; charset=utf-8" } });

/** The host origins this sandbox serves, from HOST_ORIGINS (a comma-separated list of origins). */
export const hostOrigins = (env) =>
  String(env.HOST_ORIGINS ?? "")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean);

function embedder(url, env) {
  const asked = url.searchParams.get("host");
  return asked !== null && hostOrigins(env).includes(asked) ? asked : null;
}

function declared(url) {
  const raw = url.searchParams.get("csp");
  if (raw === null) return { csp: {}, refused: [] };
  try {
    return sanitize(JSON.parse(raw));
  } catch {
    return { csp: {}, refused: [{ field: "csp", entry: raw.slice(0, 80), reason: "not JSON" }] };
  }
}

async function route(url, env) {
  if (url.pathname === "/health") return plain(200, "ok");
  const host = embedder(url, env);
  if (url.pathname === "/") {
    if (host === null) return plain(403, "This sandbox is not for that page.");
    return html(proxyPage(host), await ownPolicy(host));
  }
  if (url.pathname === "/view") {
    if (host === null) return plain(403, "This sandbox is not for that page.");
    if (!env.SIGNING_KEY) return plain(503, "The sandbox has no signing key.");
    const { csp, refused } = declared(url);
    if (!(await isSigned(env.SIGNING_KEY, host, csp, url.searchParams.get("sig")))) {
      console.log(JSON.stringify({ event: "view.unsigned" }));
      return plain(403, "This policy was not issued by the host.");
    }
    for (const item of refused) console.log(JSON.stringify({ event: "csp.refused", ...item }));
    return html(viewPage(), buildPolicy(csp, `'self' ${host}`));
  }
  return plain(404, "Not found");
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") return plain(405, "Method not allowed");
    const response = await route(new URL(request.url), env);
    return request.method === "HEAD" ? new Response(null, response) : response;
  },
};
