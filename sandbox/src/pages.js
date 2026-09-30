// SPDX-License-Identifier: AGPL-3.0-or-later
// The proxy page and the view's bootstrap page: static documents, the same for everyone except the host
// origin the proxy page names.
import { innerMain, proxyMain, iife } from "./proxy.js";

const STYLE = "html,body{margin:0;height:100%;background:transparent}iframe{display:block;width:100%;height:100%;border:0;background:transparent}";

const escapeAttribute = (text) => text.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

/** The document of the outer frame. Its policy allows its own script and style by hash and nothing else. */
export function proxyPage(hostOrigin) {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<meta name="host-origin" content="${escapeAttribute(hostOrigin)}">
<title>Card sandbox</title>
<style>${STYLE}</style>
</head>
<body>
<script>${PROXY_SCRIPT}</script>
</body>
</html>
`;
}

/** The document a view is written into. Its policy comes in the response headers, built from the declaration. */
export function viewPage() {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<title>Card</title>
<script>${VIEW_SCRIPT}</script>
</head>
<body></body>
</html>
`;
}

export const PROXY_SCRIPT = iife(proxyMain);
export const VIEW_SCRIPT = iife(innerMain);

// A bundler that keeps function names wraps them in a helper that does not exist in the browser.
for (const script of [PROXY_SCRIPT, VIEW_SCRIPT]) {
  if (script.includes("__name")) throw new Error("The sandbox scripts were built with keep_names; they would not run in a page.");
}
export const PROXY_STYLE = STYLE;
