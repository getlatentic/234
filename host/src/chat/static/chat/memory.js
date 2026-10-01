// SPDX-License-Identifier: AGPL-3.0-or-later
// <chat-memory> is the sheet "What 234 remembers" of a signed-in person, opened from a button in the chats drawer:
// their notes by kind, a title or a line changed in place, a note deleted with an Undo, a copy to keep, and
// everything deleted. The server holds the notes; this element shows them and asks for each change. It sits beside
// the drawer, not inside it, so the drawer's own dialog stays the only one in it.
import { postJson } from "./http.js";
import { instance } from "./render.js";

const KINDS = [
  ["recipient", "Recipients"],
  ["preference", "Preferences"],
  ["fact", "Facts"],
];
const NULL_ID = "0000000000000000";

customElements.define(
  "chat-memory",
  class ChatMemory extends HTMLElement {
    #forgotten = new Map();

    connectedCallback() {
      this.dialog = this.querySelector("dialog");
      this.status = this.querySelector('[data-slot="status"]');
      this.groups = this.querySelector('[data-slot="groups"]');
      this.empty = this.querySelector('[data-slot="empty"]');
      this.addEventListener("click", (event) => this.#clicked(event));
      this.addEventListener("submit", (event) => this.#saved(event));
      this.dialog.addEventListener("close", () => this.#opener()?.focus());
      document.addEventListener("click", this.#opens);
    }

    disconnectedCallback() {
      document.removeEventListener("click", this.#opens);
    }

    #opener() {
      return document.querySelector('[data-action="open-memory"]');
    }

    #opens = (event) => {
      if (event.target.closest('[data-action="open-memory"]')) this.open();
    };

    async open() {
      this.#say("");
      await this.#load();
      this.dialog.showModal();
    }

    #say(text) {
      this.status.textContent = text;
    }

    async #get() {
      const answer = await fetch(this.dataset.url, { credentials: "same-origin" });
      if (!answer.ok) throw new Error("Memory could not be read. Try again.");
      return answer.json();
    }

    async #load() {
      try {
        this.#show((await this.#get()).entries);
      } catch (problem) {
        this.#say(problem.message);
      }
    }

    #show(entries) {
      this.#forgotten.clear();
      this.groups.replaceChildren();
      for (const [kind, heading] of KINDS) {
        const mine = entries.filter((entry) => entry.kind === kind);
        if (!mine.length) continue;
        const group = instance(this, "group");
        group.querySelector('[data-slot="heading"]').textContent = heading;
        group.querySelector('[data-slot="rows"]').append(...mine.map((entry) => this.#row(entry)));
        this.groups.append(group);
      }
      this.empty.hidden = entries.length > 0;
      this.querySelector('[data-action="delete-all"]').disabled = entries.length === 0;
    }

    #row(entry) {
      const row = instance(this, "row");
      Object.assign(row.dataset, { id: entry.id, kind: entry.kind, title: entry.title, hook: entry.hook });
      row.querySelector('[data-slot="title"]').textContent = entry.title;
      row.querySelector('[data-slot="hook"]').textContent = entry.hook;
      return row;
    }

    #url(template, id) {
      return template.replace(NULL_ID, id);
    }

    #clicked(event) {
      const action = event.target.closest("[data-action]")?.dataset.action;
      const row = event.target.closest('[data-slot="row"]');
      if (event.target === this.dialog || action === "close-memory") return this.dialog.close();
      const run = {
        edit: () => this.#edit(row),
        cancel: () => this.#load(),
        forget: () => this.#forget(row),
        undo: () => this.#undo(row),
        "delete-all": () => this.#deleteAll(),
      }[action];
      run?.();
    }

    #edit(row) {
      const form = instance(this, "editing");
      form.dataset.id = row.dataset.id;
      form.dataset.kind = row.dataset.kind;
      form.querySelector('[data-slot="title-input"]').value = row.dataset.title;
      const locked = row.dataset.kind === "recipient";
      form.querySelector('[data-slot="hook-label"]').hidden = locked;
      form.querySelector('[data-slot="hook-input"]').value = row.dataset.hook;
      row.replaceWith(form);
      form.querySelector('[data-slot="title-input"]').focus();
    }

    async #saved(event) {
      event.preventDefault();
      const item = event.target.closest('[data-slot="row"]');
      const body = { title: item.querySelector('[data-slot="title-input"]').value };
      if (item.dataset.kind !== "recipient") body.hook = item.querySelector('[data-slot="hook-input"]').value;
      this.#say("");
      try {
        await postJson(this.#url(this.dataset.editUrl, item.dataset.id), body);
        await this.#load();
      } catch (problem) {
        this.#say(problem.message);
      }
    }

    async #forget(row) {
      this.#say("");
      try {
        const done = await postJson(this.#url(this.dataset.forgetUrl, row.dataset.id));
        const chip = instance(this, "forgot");
        chip.querySelector('[data-slot="text"]').textContent = `Forgot: ${done.title}`;
        chip.dataset.id = done.proposal_id;
        this.#forgotten.set(done.proposal_id, done.token);
        row.replaceWith(chip);
        chip.querySelector('[data-action="undo"]').focus();
      } catch (problem) {
        this.#say(problem.message);
      }
    }

    async #undo(chip) {
      this.#say("");
      try {
        await postJson(this.dataset.undoUrl, { proposal_id: chip.dataset.id, token: this.#forgotten.get(chip.dataset.id) });
        await this.#load();
      } catch (problem) {
        this.#say(problem.message);
      }
    }

    async #deleteAll() {
      if (!confirm("Delete everything 234 remembers? This cannot be undone.")) return;
      this.#say("");
      try {
        await postJson(this.dataset.deleteAllUrl);
        await this.#load();
      } catch (problem) {
        this.#say(problem.message);
      }
    }
  },
);
