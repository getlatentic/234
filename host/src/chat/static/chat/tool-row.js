// SPDX-License-Identifier: AGPL-3.0-or-later
import { fill } from "./render.js";

// "paystack-pay__create_payment_quote" reads as "Create payment quote"; the connector's own name stays as the tooltip.
export const readable = (tool) => {
  const words = tool.split("__").pop().replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
};

// The small word after the name; a call that worked has none.
const WORDS = { ok: "", refused: "refused", failed: "failed", stopped: "stopped" };

// A tool row is one quiet line, closed until the person opens it. Its keyboard ring (design/components.css,
// `focus-ring-target`) is drawn round the label only, and never after a pointer press: a browser that treats a
// click on a <summary> as keyboard focus would otherwise draw it.
customElements.define(
  "tool-row",
  class ToolRow extends HTMLElement {
    connectedCallback() {
      const summary = this.querySelector("summary");
      summary.addEventListener("pointerdown", () => this.toggleAttribute("data-pointer", true));
      summary.addEventListener("keydown", () => this.removeAttribute("data-pointer"));
      summary.addEventListener("blur", () => this.removeAttribute("data-pointer"));
      const name = this.querySelector('[data-slot="name"]');
      if (name.dataset.tool) return;
      this.#name(name, name.textContent);
    }

    fill({ tool, arguments: args, result_text: result, is_error: refused, cancelled }) {
      fill(this, { arguments: JSON.stringify(args ?? {}, null, 1), result });
      this.#name(this.querySelector('[data-slot="name"]'), tool);
      this.toggleAttribute("data-refused", Boolean(refused));
      this.toggleAttribute("data-stopped", Boolean(cancelled));
      this.state = !refused ? "ok" : cancelled ? "stopped" : "refused";
    }

    set state(state) {
      this.dataset.state = state;
      this.querySelector('[data-slot="status"]').textContent = WORDS[state];
    }

    #name(slot, tool) {
      slot.dataset.tool = tool;
      slot.title = tool;
      slot.textContent = readable(tool);
    }
  },
);
