// SPDX-License-Identifier: AGPL-3.0-or-later
// <chat-sheet> is the list of chats as a drawer: a modal dialog, so focus stays inside, Escape closes it
// and focus goes back to the button that opened it.
import { currentToken } from "./me.js";
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
      this.dialog.querySelectorAll("[aria-current]").forEach((other) => other.removeAttribute("aria-current"));
      const row = this.#row({ title, url, deleteUrl, mine: true });
      row.querySelector("a").setAttribute("aria-current", "page");
      this.#rows.prepend(row);
    }

    // The visitor's chats as /api/me lists them, latest first, after any row that is already there.
    fill(chats) {
      const known = new Set(Array.from(this.#rows.querySelectorAll("a"), (link) => link.getAttribute("href")));
      for (const chat of chats) if (!known.has(chat.url)) this.#rows.append(this.#row({ ...chat, title: chat.title || "New chat" }));
    }

    get #rows() {
      return this.dialog.querySelector('[data-slot="rows"]');
    }

    #row({ title, url, deleteUrl, mine }) {
      const row = instance(this, "chat-row");
      const link = row.querySelector('[data-slot="open"]');
      link.href = url;
      link.querySelector("span").textContent = title;
      const form = row.querySelector("form");
      if (!mine) form?.remove();
      else if (form) {
        form.setAttribute("action", deleteUrl);
        form.elements.csrfmiddlewaretoken.value = currentToken();
      }
      return row;
    }

    #clicked(event) {
      const onBackdrop = event.target === this.dialog;
      const current = event.target.closest("a[aria-current]");
      if (current) event.preventDefault();
      if (onBackdrop || current || event.target.closest('[data-action="close"]')) this.close();
    }
  },
);
