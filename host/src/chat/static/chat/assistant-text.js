// SPDX-License-Identifier: AGPL-3.0-or-later
// <assistant-text> shows one reply of the model as Markdown. Its text is the raw reply: the server puts it
// inside the element for stored history, and live events add to it. Every change is drawn once per animation
// frame, from the whole text, by the same renderer; while the reply is still arriving the text is settled
// first (markdown-partial.js) so half a table or an open `**` never shows.
import { renderMarkdown } from "./markdown.js";
import { settle } from "./markdown-partial.js";

// Blocks the new render leaves as they are stay in place (a scrolled table, a selection); the rest are swapped.
function reconcile(host, html) {
  const next = document.createElement("template");
  next.innerHTML = html;
  const want = [...next.content.children];
  const have = [...host.childNodes];
  have.filter((node) => node.nodeType !== Node.ELEMENT_NODE).forEach((node) => node.remove());
  const shown = have.filter((node) => node.isConnected);
  want.forEach((block, index) => {
    const old = shown[index];
    if (!old) return host.append(block);
    if (old.isEqualNode(block)) return;
    const scrolled = old.scrollLeft;
    old.replaceWith(block);
    block.scrollLeft = scrolled;
  });
  shown.slice(want.length).forEach((node) => node.remove());
}

customElements.define(
  "assistant-text",
  class AssistantText extends HTMLElement {
    #text = null;
    #frame = 0;

    connectedCallback() {
      this.#text ??= this.textContent;
      this.render();
    }

    disconnectedCallback() {
      cancelAnimationFrame(this.#frame);
      this.#frame = 0;
    }

    get text() {
      return this.#text ?? this.textContent;
    }

    // More of a reply that is still arriving.
    stream(more) {
      this.toggleAttribute("data-streaming", true);
      this.#change(this.text + more);
    }

    // The reply as it ended.
    finish(text) {
      this.toggleAttribute("data-streaming", false);
      this.#change(text);
    }

    render() {
      const text = this.text;
      reconcile(this, renderMarkdown(this.hasAttribute("data-streaming") ? settle(text) : text));
    }

    #change(text) {
      this.#text = text;
      this.#frame ||= requestAnimationFrame(() => {
        this.#frame = 0;
        this.render();
      });
    }
  },
);
