// SPDX-License-Identifier: AGPL-3.0-or-later
import { fill } from "./render.js";

const LINES = { summarised: "Earlier messages were summarised", left_out: "Earlier messages were left out" };

// The quiet line where the assistant's memory of the earlier messages was replaced by a summary. It is closed; the
// person may open it to read what the summary says. A compaction that kept no summary has nothing to open. Only
// the latest one is on the page: the thread removes the one before when a new one arrives.
customElements.define(
  "compaction-note",
  class CompactionNote extends HTMLElement {
    connectedCallback() {
      const summary = this.querySelector("summary");
      summary.addEventListener("pointerdown", () => this.toggleAttribute("data-pointer", true));
      summary.addEventListener("keydown", () => this.removeAttribute("data-pointer"));
      summary.addEventListener("blur", () => this.removeAttribute("data-pointer"));
    }

    fill({ trigger, summary }) {
      const left = trigger === "fallback";
      fill(this, { line: LINES[left ? "left_out" : "summarised"], summary: left ? "" : summary });
      this.toggleAttribute("data-plain", left || !summary);
    }
  },
);
