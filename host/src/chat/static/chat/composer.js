// SPDX-License-Identifier: AGPL-3.0-or-later
// <chat-composer> is the pill at the bottom of the page: a textarea that grows to about six lines and one
// round button that sends, or stops the reply that is streaming. It says what the person did
// ("composer:send" with the text, "composer:stop") and leaves the doing to <chat-thread>, whose `data-working`
// attribute tells it which of send and stop the button is.
import { trackKeyboard } from "./keyboard.js";

const DOCK_MS = 260;
const STOP_ARMS_MS = 400;
const DOCK_EASING = "cubic-bezier(0.2, 0.8, 0.2, 1)";

customElements.define(
  "chat-composer",
  class ChatComposer extends HTMLElement {
    #sending = false;
    #stopping = false;
    #armed = true;

    connectedCallback() {
      trackKeyboard();
      this.form = this.querySelector("form");
      this.field = this.form.elements.text;
      this.button = this.querySelector('[data-slot="send"]');
      this.form.addEventListener("submit", (event) => this.#submitted(event));
      this.field.addEventListener("input", () => this.sync());
      this.field.addEventListener("keydown", (event) => this.#keydown(event));
      this.sync();
    }

    get text() {
      return this.field.value.trim();
    }

    get working() {
      return this.closest("chat-thread")?.hasAttribute("data-working") ?? false;
    }

    // While a message is on its way the button is off.
    set sending(on) {
      this.#sending = on;
      this.sync();
    }

    // The message has gone: for a moment a button that is about to turn into Stop cannot be pressed, so a double
    // press on Send does not stop the reply it started. A message that was refused never calls this.
    sent() {
      this.#hold();
    }

    set stopping(on) {
      this.#stopping = on;
      this.sync();
    }

    // Empties the field once `sent` has gone, unless the person has already typed something else.
    clear(sent) {
      if (this.text === sent) this.field.value = "";
      this.sync();
    }

    focus() {
      this.field.focus();
    }

    // Puts text in the field. With `focus` the field takes focus and the cursor goes after the text.
    prefill(text, { focus }) {
      this.field.value = text;
      this.sync();
      if (!focus) return;
      this.field.focus();
      this.field.setSelectionRange(text.length, text.length);
    }

    // Re-reads what the button should be and how tall the field is: after typing, a clear, or a change of turn.
    sync() {
      const working = this.working;
      const stopping = working && this.#stopping;
      const held = this.#sending || !this.#armed;
      this.button.disabled = this.field.disabled || stopping || held || (!working && !this.text);
      this.button.setAttribute("aria-label", stopping ? "Stopping" : working ? "Stop" : "Send");
      this.#grow();
    }

    // Moves the pill to its new place with a short glide: measured before and after `change`, played
    // from the old place. A person who asks for less motion gets the end state at once.
    glide(change) {
      const before = this.form.getBoundingClientRect().top;
      change();
      const distance = before - this.form.getBoundingClientRect().top;
      if (!distance || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      this.form.animate([{ transform: `translateY(${distance}px)` }, { transform: "none" }], { duration: DOCK_MS, easing: DOCK_EASING });
    }

    #hold() {
      this.#armed = false;
      setTimeout(() => {
        this.#armed = true;
        this.sync();
      }, STOP_ARMS_MS);
    }

    #grow() {
      this.field.style.height = "auto";
      this.field.style.height = `${this.field.scrollHeight}px`;
    }

    #keydown(event) {
      const composing = event.isComposing || event.keyCode === 229;
      if (event.key !== "Enter" || event.shiftKey || composing) return;
      event.preventDefault();
      if (!this.working && !this.button.disabled) this.form.requestSubmit();
    }

    #submitted(event) {
      event.preventDefault();
      if (this.button.disabled) return;
      if (this.working) this.dispatchEvent(new CustomEvent("composer:stop", { bubbles: true }));
      else this.dispatchEvent(new CustomEvent("composer:send", { bubbles: true, detail: { text: this.text } }));
    }
  },
);
