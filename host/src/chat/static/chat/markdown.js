// SPDX-License-Identifier: AGPL-3.0-or-later
// A model reply as HTML. One renderer for streamed text and stored history: the server ships the raw text
// and `<assistant-text>` renders it here.
//
// What keeps it safe: raw HTML in the text is escaped (`html: false`), only http(s), mailto and tel links are
// kept, images are not rendered, and no output carries an inline style or a script, so the page's policy
// (script-src and style-src 'self') holds on top of it.
import markdownit from "./vendor/markdown-it.esm.min.mjs";
import { ALIGNED, CLASSES, CODE_BLOCK, SCROLLER } from "./markdown-style.js";

const SAFE_LINK = /^(?:https?:|mailto:|tel:)/i;
const TEXT_ALIGN = /text-align:\s*(left|center|right)/;

function classOf(token) {
  const named = CLASSES[token.type];
  return typeof named === "object" ? (named[token.tag] ?? named.default) : named;
}

function align(token) {
  const style = token.attrGet("style");
  if (style === null) return;
  token.attrs = token.attrs.filter(([name]) => name !== "style");
  const side = TEXT_ALIGN.exec(style)?.[1];
  if (side) token.attrJoin("class", ALIGNED[side]);
}

function styleTokens(state) {
  const visit = (token) => {
    const classes = classOf(token);
    if (classes) token.attrJoin("class", classes);
    if (token.type === "th_open" || token.type === "td_open") align(token);
    if (token.type === "link_open") {
      token.attrSet("target", "_blank");
      token.attrSet("rel", "noopener noreferrer");
    }
    token.children?.forEach(visit);
  };
  state.tokens.forEach(visit);
}

function build() {
  const md = markdownit({ html: false, linkify: true, breaks: true });
  md.linkify.set({ fuzzyLink: false, fuzzyEmail: false });
  md.validateLink = (url) => SAFE_LINK.test(url.trim());
  md.disable("image");
  md.core.ruler.push("chat_style", styleTokens);

  const rules = md.renderer.rules;
  const plain = (tokens, i, options, env, self) => self.renderToken(tokens, i, options);
  rules.table_open = (...args) => `<div class="${SCROLLER}">${plain(...args)}`;
  rules.table_close = (...args) => `${plain(...args)}</div>`;
  const block = (tokens, i) => `<pre class="${CODE_BLOCK}"><code>${md.utils.escapeHtml(tokens[i].content)}</code></pre>\n`;
  rules.fence = block;
  rules.code_block = block;
  return md;
}

const md = build();

// A model that read search results may leave its own citation marks in the text (【2†L1-L4】); the person is
// shown the sources on lines of their own, so the marks are taken out before the text is drawn.
const CITATION_MARK = /\s?【[^】]{0,40}】/g;

export const renderMarkdown = (text) => md.render(text.replace(CITATION_MARK, ""));
