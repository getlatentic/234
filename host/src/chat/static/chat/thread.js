// SPDX-License-Identifier: AGPL-3.0-or-later
// <chat-thread> owns the conversation on the page. The server holds the conversation; this element shows
// it: stored history arrives rendered by Django, and everything after it comes from the event stream.
import "./account.js";
import "./assistant-text.js";
import "./card-frame.js";
import "./compaction-note.js";
import "./composer.js";
import "./memory.js";
import "./sheet.js";
import "./starters.js";
import "./tool-row.js";
import { postJson } from "./http.js";
import { assistantBubble, builders, shownBubble } from "./render.js";
import { Follow } from "./scroll.js";
import { EventStream } from "./stream.js";
import { settleTools } from "./tool-status.js";

const TITLE_CHARS = 60;
// Events that cannot change what a tool row says.
const STREAMING = new Set(["text", "card_state"]);

customElements.define(
  "chat-thread",
  class ChatThread extends HTMLElement {
    seq = 0;
    #sending = false;
    #stopping = false;

    connectedCallback() {
      this.seq = Number(this.dataset.lastSeq ?? 0);
      this.thread = this.querySelector('[data-slot="thread"]');
      this.composer = this.querySelector("chat-composer");
      this.composer.addEventListener("composer:send", (event) => this.#send(event.detail.text));
      this.composer.addEventListener("composer:stop", () => this.#stop());
      this.starters = this.querySelector("chat-starters");
      this.starters.addEventListener("starter:pick", (event) => this.#pick(event.detail));
      this.sheet = this.querySelector("chat-sheet");
      this.chatsButton = this.querySelector('[data-action="chats"]');
      this.chatsButton.addEventListener("click", () => this.sheet.open());
      this.latest = this.querySelector('[data-slot="latest"]');
      this.latest.addEventListener("click", () => this.follow.jump({ smooth: true }));
      this.follow = new Follow(this, (away) => (this.latest.hidden = !away), !this.hasAttribute("data-draft"));
      this.querySelector('[data-action="share"]').addEventListener("click", (event) => this.#share(event.currentTarget));
      this.#working(this.hasAttribute("data-working"));
      settleTools(this.thread, this.hasAttribute("data-working"));
      this.stream = new EventStream({
        ticketUrl: this.dataset.ticketUrl,
        eventsUrl: this.dataset.eventsUrl,
        transport: this.dataset.transport,
        cursor: () => this.seq,
        onEvent: (event) => this.apply(event),
        onReset: () => location.reload(),
        onStatus: (state) => this.querySelector('[data-slot="offline"]').classList.toggle("hidden", state === "open"),
      });
      if (this.hasAttribute("data-draft")) return;
      this.stream.start();
      this.follow.jump();
    }

    disconnectedCallback() {
      this.stream?.stop();
    }

    apply(event) {
      if (event.seq <= this.seq) return;
      if (event.seq !== this.seq + 1) return this.stream.restart();
      try {
        this.#show(event);
      } catch (error) {
        console.error(`Could not show event ${event.seq} (${event.type})`, error);
      }
      this.seq = event.seq;
      if (!STREAMING.has(event.type)) settleTools(this.thread, this.hasAttribute("data-working"));
      this.follow.keep();
    }

    #show({ type, payload, ref }) {
      const build = builders[type];
      if (type === "compaction") this.thread.querySelector('[data-kind="compaction"]')?.remove();
      if (build) return this.thread.append(build(this, payload, { ref }));
      if (type === "text") return this.#stream(payload);
      if (type === "assistant") return this.#settle(payload);
      if (type === "round.aborted") return shownBubble(this, payload.message)?.remove();
      if (type === "card_state") return this.thread.querySelector(`card-frame[data-ref="${CSS.escape(ref)}"]`)?.push(payload.result);
      if (type === "turn.started") this.#working(true);
      if (type === "turn.finished") this.#working(false);
    }

    #stream({ message, text }) {
      const bubble = assistantBubble(this, message);
      bubble.stream(text);
      if (!bubble.isConnected) this.thread.append(bubble);
    }

    #settle({ message, text }) {
      const bubble = shownBubble(this, message);
      if (!text.trim()) return bubble?.remove();
      const shown = bubble ?? assistantBubble(this, message);
      shown.finish(text);
      if (!shown.isConnected) this.thread.append(shown);
    }

    #working(on) {
      this.toggleAttribute("data-working", on);
      if (!on) this.#stopping = false;
      this.composer.stopping = this.#stopping;
    }

    #problem(text) {
      const slot = this.querySelector('[data-slot="error"]');
      slot.textContent = text ?? "";
      slot.classList.toggle("hidden", !text);
    }

    // A starter that is a whole message goes into the field and is sent, once; the keyboard stays down after a
    // tap on a phone, where the person wants to read the answer. One that lacks something only the person knows
    // is a beginning: it goes into the field and the person finishes it, so the field has focus on a phone too.
    #pick({ text, fill }) {
      this.composer.prefill(text, { focus: fill });
      if (!fill) void this.#send(text, { focus: !matchMedia("(pointer: coarse)").matches });
    }

    async #send(text, { focus = true } = {}) {
      if (this.#sending) return;
      this.#sending = true;
      this.composer.sending = true;
      this.#problem(null);
      try {
        const { seq } = await postJson(this.hasAttribute("data-draft") ? this.dataset.startUrl : this.dataset.sendUrl, { text });
        this.composer.sent();
        this.composer.clear(text);
        this.#title(text);
        this.#opened(text.slice(0, TITLE_CHARS));
        if (this.seq < seq) this.#working(true);
        this.follow.jump();
      } catch (error) {
        this.starters.disabled = false;
        this.#problem(error.message);
      } finally {
        this.#sending = false;
        this.composer.sending = false;
        if (focus) this.composer.focus();
      }
    }

    // Stop asks the chat to end the turn; the stream then shows the reply as far as it got, and the turn's end.
    async #stop() {
      this.#stopping = true;
      this.composer.stopping = true;
      try {
        const { cancelled } = await postJson(this.dataset.cancelUrl);
        if (!cancelled) this.#working(false);
      } catch (error) {
        this.#stopping = false;
        this.composer.stopping = false;
        this.#problem(error.message);
      }
    }

    // The first message made the chat: the page is now that chat, at its own address, following its log.
    #opened(title) {
      if (!this.hasAttribute("data-draft")) return;
      this.composer.glide(() => this.removeAttribute("data-draft"));
      history.replaceState(null, "", this.dataset.pageUrl);
      this.sheet.add({ title, url: this.dataset.pageUrl, deleteUrl: this.dataset.deleteUrl });
      this.toggleAttribute("data-chats", true);
      this.chatsButton.hidden = false;
      this.stream.start();
    }

    #title(text) {
      const title = this.querySelector('[data-slot="title"]');
      if (title.textContent.trim() !== "New chat") return;
      title.textContent = document.title = text.slice(0, TITLE_CHARS);
    }

    async #share(button) {
      const { url } = await postJson(this.dataset.shareUrl);
      try {
        await navigator.clipboard.writeText(url);
        button.dataset.copied = "";
        setTimeout(() => delete button.dataset.copied, 1500);
      } catch {
        prompt("Link to open this chat on another device", url);
      }
    }
  },
);
