// SPDX-License-Identifier: AGPL-3.0-or-later
// Bundles probe-card.js with the official App class into one HTML file, served by the Worker as
// ui://paystack-pay/card-probe.html when it runs with ALT_CARDS=probe=probe-card.html.
import { writeFileSync } from "node:fs";
import { buildSync } from "esbuild";

const root = new URL("..", import.meta.url).pathname;
const built = buildSync({ entryPoints: [`${root}conformance/probe-card.js`], bundle: true, minify: true, format: "esm", write: false, platform: "browser", target: "es2022" });
const script = built.outputFiles[0].text.replaceAll("</script", "<\\/script");
const html = `<!doctype html><meta charset="utf-8"><title>probe</title><pre id="out" style="font:12px monospace"></pre><script type="module">${script}</script>`;
const target = `${root}checkout/src/checkout/card/probe-card.html`;
writeFileSync(target, html);
console.log(`${target}: ${html.length.toLocaleString()} bytes`);
