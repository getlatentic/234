// SPDX-License-Identifier: AGPL-3.0-or-later
// <chat-connected> is the sheet "Connected apps" of a signed-in person, opened from a button in the chats drawer:
// the apps and personal agents that can act for them, and the Brands where 234 acts for them, each with what it
// can use and a Disconnect that ends it at once. The server holds the grants; this element shows them and asks for each ending.
import { postJson } from "./http.js";
import { instance } from "./render.js";

customElements.define(
  "chat-connected",
  class ChatConnected extends HTMLElement {
    connectedCallback() {
      this.dialog = this.querySelector("dialog");
      this.status = this.querySelector('[data-slot="status"]');
      this.note = this.querySelector('[data-slot="note"]');
      this.rows = this.querySelector('[data-slot="rows"]');
      this.empty = this.querySelector('[data-slot="empty"]');
      this.addEventListener("click", (event) => this.#clicked(event));
      this.dialog.addEventListener("close", () => document.querySelector('[data-action="open-connected"]')?.focus());
      document.addEventListener("click", this.#opens);
    }

    disconnectedCallback() {
      document.removeEventListener("click", this.#opens);
    }

    #opens = (event) => {
      if (event.target.closest('[data-action="open-connected"]')) this.open();
    };

    async open() {
      this.status.textContent = this.note.textContent = "";
      try {
        const answer = await fetch(this.dataset.url, { credentials: "same-origin" });
        if (!answer.ok) throw new Error("Connected apps could not be read. Try again.");
        this.#show((await answer.json()).connections);
      } catch (problem) {
        this.status.textContent = problem.message;
      }
      this.dialog.showModal();
    }

    #show(connections) {
      this.rows.replaceChildren(...connections.map((connection) => this.#row(connection)));
      this.empty.hidden = connections.length > 0;
    }

    #row({ kind, id, name, uses }) {
      const row = instance(this, "row");
      Object.assign(row.dataset, { kind, id, name });
      row.querySelector('[data-slot="name"]').textContent = name;
      row.querySelector('[data-slot="uses"]').textContent = uses;
      row.querySelector('[data-action="end"]').setAttribute("aria-label", `Disconnect ${name}`);
      return row;
    }

    async #end(row) {
      if (!confirm(`Disconnect ${row.dataset.name}? It stops working for you at once.`)) return;
      this.status.textContent = this.note.textContent = "";
      try {
        const answer = await postJson(this.dataset.endUrl, { kind: row.dataset.kind, id: row.dataset.id });
        this.#show(answer.connections);
        this.note.textContent = answer.note ?? "";
        this.querySelector('[data-action="close-connected"]').focus();
      } catch (problem) {
        this.status.textContent = problem.message;
      }
    }

    #clicked(event) {
      const action = event.target.closest("[data-action]")?.dataset.action;
      if (event.target === this.dialog || action === "close-connected") return this.dialog.close();
      if (action === "end") this.#end(event.target.closest('[data-slot="row"]'));
    }
  },
);
