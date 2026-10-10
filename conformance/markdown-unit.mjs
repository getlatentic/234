// SPDX-License-Identifier: AGPL-3.0-or-later
// The Markdown renderer and the settling of a half-arrived reply, as strings: no browser and no stack.
// usage: node conformance/markdown-unit.mjs
import { renderMarkdown } from "../host/src/chat/static/chat/markdown.js";
import { settle } from "../host/src/chat/static/chat/markdown-partial.js";
import { HOSTILE, SAMPLE } from "./markdown-fixtures.mjs";
import { suite } from "./lib.mjs";

const { check, finish } = suite("Markdown");
const visible = (html) => html.replace(/<[^>]+>/g, "").replaceAll("&lt;", "<").replaceAll("&gt;", ">").replaceAll("&amp;", "&");
const drawn = (text) => renderMarkdown(settle(text));

console.log("\nrendering");
const html = renderMarkdown(SAMPLE);
check(/<h1 [^>]*>Plan<\/h1>/.test(html), "a heading");
check(/<strong>the summary<\/strong>/.test(html) && /<em>emphasis<\/em>/.test(html) && /<s>old<\/s>/.test(html), "bold, italic and strikethrough");
check(/<code [^>]*>inline code<\/code>/.test(html), "inline code");
check(/<ul [^>]*>\s*<li [^>]*>first <strong>item<\/strong><\/li>/.test(html) && /<ol [^>]*>\s*<li [^>]*>one<\/li>/.test(html), "bulleted and numbered lists");
check(/<div class="overflow-x-auto"><table [^>]*tabular-nums[^>]*>/.test(html), "a table inside a scrolling wrapper, with tabular numbers");
check(/<th [^>]*text-right[^>]*>Qty<\/th>/.test(html) && !/style=/.test(html), "column alignment becomes a class, never an inline style");
check(/<pre [^>]*><code>const total = 2 \* 3;\n<\/code><\/pre>/.test(html), "a fenced code block, its text untouched");
check(/<a href="https:\/\/example.com\/docs" [^>]*target="_blank" rel="noopener noreferrer">the docs<\/a>/.test(html), "a link opens in a new tab with rel noopener noreferrer");
check(/<br>/.test(renderMarkdown("one\ntwo")), "a single newline stays a line break, as it did in plain text");
check(visible(renderMarkdown("It ended 3-3 【2†L1-L4】. Next week【3†L7】!")) === "It ended 3-3. Next week!\n", "a model's citation marks are taken out");
check(!/<a /.test(renderMarkdown("run main.py and read notes.md")), "a file name is not turned into a link");
check(/<a href="https:\/\/example.org"/.test(renderMarkdown("see https://example.org now")), "a full web address is linked");

console.log("\nraw HTML and links from a reply");
check(renderMarkdown("<b>x</b>").includes("&lt;b&gt;x&lt;/b&gt;"), "raw HTML is escaped, not passed on");
const TAGS = new Set("p h1 h2 h3 h4 h5 h6 ul ol li blockquote hr code pre strong em s a br table thead tbody tr th td div".split(" "));
const ATTRIBUTES = new Set(["class", "href", "target", "rel", "title"]);
const SAFE_HREF = /^(https?:|mailto:|tel:)/i;

/** The tags and attributes that survive in rendered output, the way a parser would read them. */
function stray(html) {
  const found = [];
  for (const [, name, rest] of html.matchAll(/<\/?([a-zA-Z][\w-]*)([^>]*)>/g)) {
    if (!TAGS.has(name.toLowerCase())) found.push(`<${name}>`);
    for (const [, attribute, , value] of rest.matchAll(/([\w-]+)(=("[^"]*"|\S+))?/g)) {
      if (!ATTRIBUTES.has(attribute)) found.push(`${attribute} attribute`);
      if (attribute === "href" && !SAFE_HREF.test((value ?? "").slice(1, -1))) found.push(`href ${value}`);
    }
  }
  return found;
}
for (const text of HOSTILE) {
  const out = renderMarkdown(text);
  check(stray(out).length === 0, `hostile text is inert: ${text.replaceAll("\n", "\\n").slice(0, 70)}${stray(out).length ? ` (${stray(out)})` : ""}`);
}
check(stray('<img src=x onerror="x">').length > 0 && stray('<a href="javascript:x" target="_blank">').length > 0, "the check itself sees a tag or an attribute that should not be there");

console.log("\na reply that is still arriving");
const settled = [
  ["an open bold is closed for now", "**bold te", "**bold te**"],
  ["a marker with nothing after it waits", "text **", "text "],
  ["half a closing marker is completed", "**bold*", "**bold**"],
  ["an open italic is closed", "a *it", "a *it*"],
  ["snake_case is not emphasis", "snake_case_name", "snake_case_name"],
  ["an open code span is closed", "use `foo", "use `foo`"],
  ["an unfinished link shows its label", "read [the do", "read the do"],
  ["a link that is finished is kept", "[a](https://x.org)", "[a](https://x.org)"],
  ["a lone # waits", "text\n\n##", "text\n"],
  ["half a closing fence waits", "```js\ncode\n``", "```js\ncode\n"],
  ["a lone dash waits", "- a\n-", "- a"],
  ["a table header waits for its delimiter row", "| a | b |", ""],
  ["a delimiter row being typed waits", "| a | b |\n|---|", ""],
  ["a formed table shows its header", "| a | b |\n|---|---|", "| a | b |\n|---|---|"],
  ["an unfinished row is held back", "| a | b |\n|---|---|\n| 1 | 2", "| a | b |\n|---|---|"],
  ["a finished row is shown", "| a | b |\n|---|---|\n| 1 | 2 |\n", "| a | b |\n|---|---|\n| 1 | 2 |\n"],
  ["a code block is left as it is", "```js\nconst a = **x", "```js\nconst a = **x"],
  ["text before a table stays", "Totals:\n| a | b |\n|---|---|\n| 1 |", "Totals:\n| a | b |\n|---|---|"],
];
for (const [what, input, expected] of settled) check(settle(input) === expected, `${what}: ${JSON.stringify(input)}`);
check(settle("**done**") === "**done**" && settle(SAMPLE) === SAMPLE, "a reply that is whole is not changed by settling");

console.log("\nevery prefix of a reply, as it streams");
let flicker = 0;
let raw = 0;
for (let n = 1; n <= SAMPLE.length; n += 1) {
  const text = visible(drawn(SAMPLE.slice(0, n)));
  if (/\*\*|~~|\]\(|^\||\n\||`{2,}/m.test(text)) {
    raw += 1;
    if (raw === 1) console.log(`    first raw marker at ${n}: ${JSON.stringify(SAMPLE.slice(0, n).slice(-40))} -> ${JSON.stringify(text.slice(-60))}`);
  }
  if (n > 1 && !visible(drawn(SAMPLE.slice(0, n - 1))).trim().length && text.trim().length > 200) flicker += 1;
}
check(raw === 0, `no prefix of ${SAMPLE.length} draws a raw marker (** ~~ ]( | or a fence)`);
check(flicker === 0, "text never appears all at once from nothing");
finish();
