// SPDX-License-Identifier: AGPL-3.0-or-later
// A host page built on the official ext-apps AppBridge, as the reference the cards are tested against.
import { AppBridge, PostMessageTransport } from "@modelcontextprotocol/ext-apps/app-bridge";

const CARD_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:";
const PAYSTACK_CSP = "default-src 'none'; script-src 'unsafe-inline' https://js.paystack.co; style-src 'unsafe-inline'; img-src data:; font-src data:; frame-src https://checkout.paystack.com";
const log = (window.__log = []);
const record = (kind, detail) => log.push({ kind, detail });

const post = (path, body) =>
  fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json());

// What a host says about itself, for the runs that need a host that does or does not offer Paystack's popup:
//   plain (default)      declares nothing about a sandbox or display modes
//   claims               lists Paystack's origins as approved, lets the card have them, offers full screen and refuses it
//   no-fullscreen        lists the origins, offers inline only
//   blocks               lists the origins and goes full screen, but its own policy for the card does not allow them
const PAYSTACK = { resourceDomains: ["https://js.paystack.co"], frameDomains: ["https://checkout.paystack.com"] };
const HOSTS = {
  plain: { capabilities: {}, context: {} },
  claims: { capabilities: { sandbox: { csp: PAYSTACK } }, context: { displayMode: "inline", availableDisplayModes: ["inline", "fullscreen"] } },
  "no-fullscreen": { capabilities: { sandbox: { csp: PAYSTACK } }, context: { displayMode: "inline", availableDisplayModes: ["inline"] } },
  blocks: { capabilities: { sandbox: { csp: PAYSTACK } }, context: { displayMode: "inline", availableDisplayModes: ["inline", "fullscreen"] } },
};

async function mount(uri, variant = "plain") {
  const host = HOSTS[variant];
  const quote = await post("/api/quote", {});
  const html = await (await fetch(`/api/card?uri=${encodeURIComponent(uri)}`)).text();
  const frame = document.getElementById("card");
  const bridge = new AppBridge(null, { name: "conformance-host", version: "0.1.0" }, { openLinks: {}, serverTools: {}, updateModelContext: { text: {} }, ...host.capabilities }, { hostContext: host.context });
  bridge.onrequestdisplaymode = async ({ mode }) => {
    record("displaymode", mode);
    return { mode: variant === "blocks" && mode === "fullscreen" ? "fullscreen" : "inline" };
  };
  bridge.oncalltool = async (params) => {
    record("calltool", params.name);
    const answer = await post("/api/call", { name: params.name, arguments: params.arguments ?? {} });
    if (answer.refused) throw new Error(answer.refused);
    return answer;
  };
  bridge.onopenlink = async (params) => {
    record("openlink", params.url);
    return /^https?:\/\//i.test(params.url) ? {} : { isError: true };
  };
  bridge.onmessage = async (params) => {
    record("message", params.content?.[0]?.text ?? "");
    return {};
  };
  bridge.onupdatemodelcontext = async (params) => {
    record("modelcontext", params.content?.[0]?.text ?? "");
    return {};
  };
  bridge.addEventListener("sizechange", (size) => {
    record("size", size.height);
    if (size.height) frame.style.height = `${Math.ceil(size.height)}px`;
  });
  bridge.addEventListener("initialized", () => {
    record("initialized", JSON.stringify(bridge.getAppCapabilities?.() ?? {}));
    void bridge.sendToolInput({ arguments: {} });
    void bridge.sendToolResult(quote);
  });
  await bridge.connect(new PostMessageTransport(frame.contentWindow, frame.contentWindow));
  const meta = /<head[^>]*>/i;
  const policy = variant === "claims" ? PAYSTACK_CSP : CARD_CSP;
  frame.srcdoc = meta.test(html) ? html.replace(meta, (head) => `${head}<meta http-equiv="Content-Security-Policy" content="${policy}">`) : html;
  window.__quote = quote;
}

window.__mount = mount;
document.title = "conformance host";
