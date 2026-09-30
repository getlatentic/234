// SPDX-License-Identifier: AGPL-3.0-or-later
// <card-frame> shows a connector's card behind the sandbox proxy and is the host side of its JSON-RPC: the
// official ext-apps AppBridge answers the card, and this element relays what the card asks for to the chat (a
// tool call, a note or message for the model, a link) through the host's own endpoints.
//
// The frame in the page is the proxy, served by the sandbox Worker from another origin; the card's HTML is
// fetched here (with the origins it may use, already checked by the server) and sent to the proxy, which
// writes it into a frame of its own under the policy those origins make.
import { AppBridge } from "../app-bridge.min.js";
import { FullScreen } from "./card-fullscreen.js";
import { DISPLAY_MODES, hostContext, watchContext } from "./host-context.js";
import { postJson } from "./http.js";
import { SandboxTransport } from "./sandbox-transport.js";

const PROXY_TIMEOUT_MS = 10_000;
const HOST_CAPABILITIES = { openLinks: {}, serverTools: {}, logging: {}, updateModelContext: { text: {} }, message: { text: {} } };
const CHAT_PATH = /^\/c\/[0-9a-f]{32}\/?$/;
const SIMULATED_CHECKOUT = "/sim/checkout/";
const NOTE = "m-0 mb-1 text-xs text-ink-3 in-[.fixed]:px-3 in-[.fixed]:py-1.5";
const BORDERED = ["border", "border-line", "bg-raised", "rounded-card"];

/** The simulated checkout is told which chat it was opened from, so it can offer the way back. */
const withWayBack = (url) => {
  const link = new URL(url);
  if (link.pathname.startsWith(SIMULATED_CHECKOUT) && CHAT_PATH.test(location.pathname)) {
    link.searchParams.set("back", location.pathname);
  }
  return link.href;
};
const FEATURES = { camera: "camera", microphone: "microphone", geolocation: "geolocation", clipboardWrite: "clipboard-write" };
/** The permission-policy list for the proxy's frame: only what the host granted, which the proxy hands on to the card. */
const allowAttribute = (granted) =>
  Object.entries(FEATURES)
    .filter(([name]) => granted?.[name] !== undefined)
    .map(([, feature]) => feature)
    .join("; ");
/** A card names itself for the frame's title and the full-screen bar: a short line of plain text, whatever it sent. */
const label = (title) => (typeof title === "string" ? title.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, 40) || undefined : undefined);
const textOf = (params) => params?.content?.find((block) => block.type === "text")?.text;
const jsonIn = (root, selector) => {
  const script = root.querySelector(selector);
  return script ? JSON.parse(script.textContent) : null;
};
const timeout = (ms) => new Promise((_, reject) => setTimeout(() => reject(new Error("The sandbox did not answer.")), ms));

/** "This card loads content from a.example and b.example": read before the card is used, never a dialog. */
export function loadsFrom(hosts) {
  const shown = hosts.slice(0, 3);
  const rest = hosts.length - shown.length;
  const names = rest > 0 ? `${shown.join(", ")} and ${rest} more` : shown.length > 1 ? `${shown.slice(0, -1).join(", ")} and ${shown.at(-1)}` : shown[0];
  return `This card loads content from ${names}`;
}

customElements.define(
  "card-frame",
  class CardFrame extends HTMLElement {
    #bridge = null;
    #screen = null;
    #context = null;
    #unwatch = null;
    #inlineHeight = "";
    #ready = false;
    #waiting = [];

    connectedCallback() {
      if (this.#bridge) return;
      const stored = [jsonIn(this, 'script[id^="card-"]'), jsonIn(this, 'script[id^="state-"]')];
      this.results ??= stored.filter(Boolean);
      addEventListener("pagehide", this.#teardown);
      this.#mount().catch((error) => this.#unavailable(error));
    }

    disconnectedCallback() {
      removeEventListener("pagehide", this.#teardown);
      this.#screen?.leave();
      this.#unwatch?.();
      this.#bridge?.close?.();
    }

    /** The card is told before its page goes; once the frame is removed there is nobody to tell. */
    #teardown = () => {
      if (this.#ready) void this.#bridge.teardownResource({ reason: "The page is closing." }).catch(() => undefined);
    };

    /** A newer state of the card's quote: from this tab, another tab, or a payment webhook. */
    push(result) {
      if (this.#ready) void this.#bridge.sendToolResult(result);
      else this.#waiting.push(result);
    }

    #unavailable(error) {
      console.error("The card could not be shown", error);
      const frame = this.querySelector("iframe");
      const note = document.createElement("p");
      note.className = NOTE;
      note.setAttribute("role", "status");
      note.textContent = "This card could not be shown.";
      frame.replaceWith(note);
    }

    /** Tells the card what changed about where it is shown. The bridge keeps the whole context, so the change is made on it. */
    #update(changes = {}) {
      const frame = this.querySelector("iframe");
      const mode = changes.displayMode ?? this.#context.displayMode;
      this.#context = { ...hostContext(frame, mode), ...changes };
      this.#bridge.setHostContext(this.#context);
    }

    /** Gives the card the display mode it asked for, if the host offers it, and tells it what it now has. */
    #present(mode) {
      const declared = this.#bridge.getAppCapabilities()?.availableDisplayModes;
      if (!DISPLAY_MODES.includes(mode) || (declared && !declared.includes(mode))) return this.#context.displayMode;
      const frame = this.querySelector("iframe");
      if (mode === "fullscreen") this.#screen.enter(frame.title);
      else {
        this.#screen.leave();
        if (this.#inlineHeight) frame.style.height = this.#inlineHeight;
      }
      const now = this.#screen.active ? "fullscreen" : "inline";
      this.#update({ displayMode: now });
      return now;
    }

    #relay(bridge, thread, server) {
      bridge.oncalltool = async (params) => {
        try {
          return await postJson(thread.callUrl, { server, name: params.name, arguments: params.arguments ?? {} });
        } catch (error) {
          throw new Error(error.message);
        }
      };
      bridge.onopenlink = async ({ url }) => {
        if (!/^https?:\/\//i.test(url ?? "")) return { isError: true };
        window.open(withWayBack(url), "_blank", "noopener,noreferrer");
        return {};
      };
      bridge.onupdatemodelcontext = async (params) => {
        const text = textOf(params);
        if (text) await postJson(thread.contextUrl, { text });
        return {};
      };
      bridge.onmessage = async (params) => {
        const text = textOf(params);
        if (!text) throw new Error("A message needs text content.");
        await postJson(thread.messageUrl, { text });
        return {};
      };
      bridge.onloggingmessage = (params) => console.info("[card]", params.level, params.data);
      bridge.onrequestdisplaymode = async ({ mode }) => ({ mode: this.#present(mode) });
    }

    /** Fetches the card and what it may use, opens the proxy, and gives the card to it once it says it is ready. */
    async #load(bridge, transport, frame, thread) {
      const server = this.dataset.server;
      const answer = await fetch(`${thread.cardUrl}?${new URLSearchParams({ server, uri: this.dataset.uri })}`, { credentials: "same-origin" });
      const card = await answer.json();
      if (!answer.ok) throw new Error(card.error ?? "The card was refused.");
      if (card.hosts.length) this.#say(frame, loadsFrom(card.hosts));
      if (card.prefersBorder === true) frame.classList.add(...BORDERED);
      const allow = allowAttribute(card.permissions);
      if (allow) frame.setAttribute("allow", allow);
      frame.src = `${thread.sandboxOrigin}/?${new URLSearchParams({ host: location.origin })}`;
      await Promise.race([transport.ready, timeout(PROXY_TIMEOUT_MS)]);
      await bridge.sendSandboxResourceReady({ html: card.html, sandbox: card.sandbox, csp: card.csp, permissions: card.permissions, signature: card.signature });
    }

    #say(frame, text) {
      const line = document.createElement("p");
      line.className = NOTE;
      line.id = `domains-${this.dataset.ref}`;
      line.textContent = text;
      frame.before(line);
      frame.setAttribute("aria-describedby", line.id);
    }

    async #mount() {
      const frame = this.querySelector("iframe");
      const thread = this.closest("chat-thread").dataset;
      if (!thread.sandboxOrigin) throw new Error("No sandbox origin is configured.");
      this.#context = hostContext(frame);
      const bridge = new AppBridge(null, { name: "checkout-host", version: "0.1.0" }, { ...HOST_CAPABILITIES, sandbox: JSON.parse(thread.sandbox) }, {
        hostContext: this.#context,
      });
      this.#bridge = bridge;
      this.#screen = new FullScreen(this, frame);
      this.#screen.onclose = () => this.#present("inline");
      this.#relay(bridge, thread, this.dataset.server);
      bridge.addEventListener("sizechange", ({ height }) => {
        if (!height || this.#screen.active) return;
        this.#inlineHeight = `${Math.ceil(height)}px`;
        frame.style.height = this.#inlineHeight;
      });
      bridge.addEventListener("initialized", () => {
        frame.title = label(bridge.getAppVersion()?.title) ?? frame.title;
        void bridge.sendToolInput({ arguments: {} });
        for (const result of [...this.results, ...this.#waiting]) void bridge.sendToolResult(result);
        this.#waiting = [];
        this.#ready = true;
        this.#unwatch = watchContext(frame, () => this.#update());
      });
      const transport = new SandboxTransport(frame, thread.sandboxOrigin);
      await bridge.connect(transport);
      await this.#load(bridge, transport, frame, thread);
    }
  },
);
