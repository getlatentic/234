// SPDX-License-Identifier: AGPL-3.0-or-later
// A card written on the official ext-apps App class, used to test hosts: it exposes every call a card can make
// as window.probe, and records what the host answered. Not a product card.
import { App } from "@modelcontextprotocol/ext-apps";

const out = document.getElementById("out");
const app = new App({ name: "probe-card", version: "0.1.0" }, {}, { autoResize: true });
window.__probe = { events: [], results: [] };
const note = (kind, detail) => {
  window.__probe.events.push({ kind, detail });
  out.textContent += `${kind}: ${JSON.stringify(detail).slice(0, 120)}\n`;
};
app.addEventListener("toolresult", (result) => {
  window.__probe.quote = result.structuredContent?.quote;
  window.__probe.token = result._meta?.approvalToken;
  note("toolresult", result.structuredContent?.quote?.id ?? "no quote");
});
app.addEventListener("toolinput", (input) => note("toolinput", input.arguments));

const record = async (name, work) => {
  try {
    const value = await work();
    window.__probe.results.push({ name, ok: true, value });
    return value;
  } catch (error) {
    window.__probe.results.push({ name, ok: false, error: String(error.message ?? error) });
    return undefined;
  }
};

window.probe = {
  callTool: (name, args) => record(`tools/call ${name}`, () => app.callServerTool({ name, arguments: args })),
  message: (text) => record("ui/message", () => app.sendMessage({ role: "user", content: [{ type: "text", text }] })),
  context: (text) => record("ui/update-model-context", () => app.updateModelContext({ content: [{ type: "text", text }] })),
  openLink: (url) => record("ui/open-link", () => app.openLink({ url })),
};

await app.connect();
note("connected", app.getHostContext?.() ?? {});
