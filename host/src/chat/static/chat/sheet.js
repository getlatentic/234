// SPDX-License-Identifier: AGPL-3.0-or-later
// <chat-sheet> is the list of chats. On a narrow screen it is a drawer: a modal dialog, so focus stays inside,
// Escape closes it and focus goes back to the button that opened it. On a wide screen it is a sidebar docked at
// the left, open until the person closes it, and what they chose is remembered.
import { currentToken } from "./me.js";
import { instance } from "./render.js";

const WIDE = window.matchMedia("(min-width: 64rem)");
const REMEMBERED = "234.sidebar";
const chosen = () => {
  try {
    return localStorage.getItem(REMEMBERED);
  } catch {
    return null;
  }
};
const choose = (value) => {
  try {
    localStorage.setItem(REMEMBERED, value);
  } catch {}
};

customElements.define(
  "chat-sheet",
  class ChatSheet extends HTMLElement {
    connectedCallback() {
      this.dialog = this.querySelector("dialog");
      this.dialog.addEventListener("click", (event) => this.#clicked(event));
      this.dialog.addEventListener("close", () => {
        document.body.classList.remove("overflow-hidden");
        this.#thread?.toggleAttribute("data-sidebar", false);
      });
      WIDE.addEventListener("change", () => this.restore());
      this.restore();
      this.dialog.addEventListener("submit", (event) => {
        if (event.target.matches("[data-confirm]") && !confirm("Delete this chat?")) event.preventDefault();
      });
    }

    get #thread() {
      return this.closest("chat-thread");
    }

    get #docked() {
      return this.dialog.open && !this.dialog.matches(":modal");
    }

    // The sidebar is open on a wide screen unless the person closed it; a narrow screen shows no sidebar.
    restore() {
      const offered = this.#thread?.hasAttribute("data-chats");
      const shown = WIDE.matches && offered && chosen() !== "closed";
      if (shown && !this.dialog.open) {
        this.dialog.show();
        if (this.dialog.contains(document.activeElement)) document.activeElement.blur();
      }
      if (!shown && this.#docked) this.dialog.close();
      this.#thread?.toggleAttribute("data-sidebar", shown);
    }

    open() {
      if (WIDE.matches) {
        choose("open");
        return this.restore();
      }
      document.body.classList.add("overflow-hidden");
      this.dialog.showModal();
    }

    close() {
      if (this.#docked) choose("closed");
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
      const closer = event.target.closest('[data-action="close"]');
      if (this.#docked) return closer && this.close();
      const onBackdrop = event.target === this.dialog;
      const current = event.target.closest("a[aria-current]");
      if (current) event.preventDefault();
      if (onBackdrop || current || closer) this.close();
    }
  },
);
