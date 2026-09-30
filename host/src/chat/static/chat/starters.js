// SPDX-License-Identifier: AGPL-3.0-or-later
// <chat-starters> is the row of suggestions on the empty home. A starter that is a whole message is sent: the
// press says which one ("starter:pick", `fill` false) and every button is off from that moment, so one press is
// one message and a second press, on the same card or another, cannot send again; the thread turns them back on
// if the send fails. A starter that lacks something only the person knows (`data-fill`) is only offered as a
// beginning: "starter:pick" carries `fill` true, nothing is disabled, and the starters stay until a message goes.
customElements.define(
  "chat-starters",
  class ChatStarters extends HTMLElement {
    connectedCallback() {
      this.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-text]");
        if (!button || button.disabled) return;
        const fill = button.hasAttribute("data-fill");
        if (!fill) this.disabled = true;
        this.dispatchEvent(new CustomEvent("starter:pick", { bubbles: true, detail: { text: button.dataset.text, fill } }));
      });
    }

    set disabled(off) {
      this.querySelectorAll("button").forEach((button) => (button.disabled = off));
    }
  },
);
