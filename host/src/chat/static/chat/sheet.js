// SPDX-License-Identifier: AGPL-3.0-or-later
// <chat-sheet> is the list of chats as a drawer: a modal dialog, so focus stays inside, Escape closes it
// and focus goes back to the button that opened it.
import { instance } from "./render.js";

customElements.define(
  "chat-sheet",
  class ChatSheet extends HTMLElement {
    connectedCallback() {
      this.dialog = this.querySelector("dialog");
      this.dialog.addEventListener("click", (event) => this.#clicked(event));
      this.dialog.addEventListener("close", () => document.body.classList.remove("overflow-hidden"));
      this.dialog.addEventListener("submit", (event) => {
        if (event.target.matches("[data-confirm]") && !confirm("Delete this chat?")) event.preventDefault();
      });
    }

    open() {
      document.body.classList.add("overflow-hidden");
      this.dialog.showModal();
    }

    close() {
      this.dialog.close();
    }

    // The chat that has just been made: first in the list, marked as the one on show.
    add({ title, url, deleteUrl }) {
      const row = instance(this, "chat-row");
      const link = row.querySelector('[data-slot="open"]');
      link.href = url;
      link.querySelector("span").textContent = title;
      row.querySelector("form")?.setAttribute("action", deleteUrl);
      this.dialog.querySelectorAll("[aria-current]").forEach((other) => other.removeAttribute("aria-current"));
      link.setAttribute("aria-current", "page");
      this.dialog.querySelector('[data-slot="rows"]').prepend(row);
    }

    #clicked(event) {
      const onBackdrop = event.target === this.dialog;
      const current = event.target.closest("a[aria-current]");
      if (current) event.preventDefault();
      if (onBackdrop || current || event.target.closest('[data-action="close"]')) this.close();
    }
  },
);
