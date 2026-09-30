// SPDX-License-Identifier: AGPL-3.0-or-later
// A host page on the official ext-apps AppBridge that shows one tool result in a card, for the
// state screenshots and the interaction checks of card-states.mjs.
import { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge";

const CARD_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:";
const log = (window.__log = []);
window.__height = 0;

// `result` is what the host sends as the tool result; every later tools/call from the card is answered
// with `answer` (default: the same result), or by the page's __forward hook when the test wires the card to a Worker, so a polling card keeps showing the state under test.
window.__mount = async ({ html, result, answer, scheme, notice, hostContext = {}, csp = CARD_CSP }) => {
  const frame = document.getElementById("card");
  const bridge = new AppBridge(
    null,
    { name: "card-states-host", version: "0.1.0" },
    { openLinks: {}, serverTools: {}, updateModelContext: { text: {} } },
    { hostContext: { theme: scheme, ...hostContext } },
  );
  // A host that offers the display modes it lists: the page's own CSS makes the frame fill the window.
  bridge.onrequestdisplaymode = async ({ mode }) => {
    log.push({ kind: "displaymode", mode });
    const granted = (hostContext.availableDisplayModes ?? ["inline"]).includes(mode) ? mode : (window.__mode ?? "inline");
    window.__mode = granted;
    document.body.dataset.mode = granted;
    bridge.setHostContext({ displayMode: granted });
    return { mode: granted };
  };
  bridge.oncalltool = async (params) => {
    log.push({ kind: "calltool", name: params.name, args: params.arguments ?? {} });
    return window.__forward ? window.__forward(params.name, params.arguments ?? {}) : (answer ?? result);
  };
  bridge.onopenlink = async (params) => {
    log.push({ kind: "openlink", url: params.url });
    return {};
  };
  bridge.onmessage = async () => ({});
  bridge.onupdatemodelcontext = async (params) => {
    log.push({ kind: "modelcontext", text: params.content?.[0]?.text ?? "" });
    return {};
  };
  bridge.addEventListener("sizechange", (size) => {
    if (size.height) frame.style.height = `${Math.ceil(size.height)}px`;
    window.__height = Math.ceil(size.height ?? 0);
  });
  bridge.addEventListener("initialized", async () => {
    log.push({ kind: "initialized" });
    void bridge.sendToolInput({ arguments: {} });
    await bridge.sendToolResult(result);
    if (notice) await bridge.sendToolResult({ isError: true, content: [{ type: "text", text: notice }] });
  });
  window.__bridge = bridge;
  await bridge.connect(new PostMessageTransport(frame.contentWindow, frame.contentWindow));
  const head = /<head[^>]*>/i;
  frame.srcdoc = head.test(html) ? html.replace(head, (h) => `${h}<meta http-equiv="Content-Security-Policy" content="${csp}">`) : html;
};
