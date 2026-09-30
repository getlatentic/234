// SPDX-License-Identifier: AGPL-3.0-or-later
// The AppBridge's transport to a card that lives behind the sandbox proxy (ext-apps specification 2026-01-26,
// "Sandbox proxy"). It differs from the SDK's PostMessageTransport in what the standard asks of a web host:
//   - it talks to the proxy's window at the sandbox origin, never to "*", and hears only that window and origin;
//   - `ui/notifications/sandbox-proxy-ready` is the proxy's own message and is answered here, not by the bridge;
//   - nothing but sandbox messages and responses goes to the view before it has sent `initialized`; a request or
//     notification the bridge sends earlier waits and goes out, in order, right after.
import { PostMessageTransport } from "../app-bridge.min.js";

const PROXY_READY = "ui/notifications/sandbox-proxy-ready";
const INITIALIZED = "ui/notifications/initialized";
const RESERVED = "ui/notifications/sandbox-";

const isMessageToView = (message) => typeof message.method === "string" && !message.method.startsWith(RESERVED);

export class SandboxTransport extends PostMessageTransport {
  #initialized = false;
  #held = [];
  #proxyReady;
  ready = new Promise((resolve) => (this.#proxyReady = resolve));

  constructor(frame, origin) {
    const proxy = frame.contentWindow;
    super({ postMessage: (message) => proxy.postMessage(message, origin) }, proxy);
    const accept = this.messageListener;
    this.messageListener = (event) => {
      if (event.source !== proxy || event.origin !== origin) return;
      if (event.data?.method === PROXY_READY) return this.#proxyReady();
      accept(event);
      if (event.data?.method === INITIALIZED) this.#release();
    };
  }

  /** Sends now, or holds a request or notification for the view until the view has initialized. */
  async send(message, options) {
    if (isMessageToView(message) && !this.#initialized) {
      this.#held.push([message, options]);
      return;
    }
    await super.send(message, options);
  }

  #release() {
    this.#initialized = true;
    const held = this.#held;
    this.#held = [];
    for (const [message, options] of held) void super.send(message, options);
  }
}
