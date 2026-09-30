// SPDX-License-Identifier: AGPL-3.0-or-later
// The same McpApp surface as mcp-app.js, on the official ext-apps App class. Bundled by build.py --client official.
import { App } from "@modelcontextprotocol/ext-apps";

const EVENTS = {
  "ui/notifications/tool-result": "toolresult",
  "ui/notifications/tool-input": "toolinput",
  "ui/notifications/tool-cancelled": "toolcancelled",
  "ui/notifications/host-context-changed": "hostcontextchanged",
};

const app = new App({ name: "234 card", version: "0.1.0" }, {}, { autoResize: true });

window.McpApp = {
  on(method, handler) {
    if (EVENTS[method]) app.addEventListener(EVENTS[method], handler);
    else if (method === "ui/resource-teardown") app.onteardown = async () => ({});
  },
  async connect() {
    await app.connect();
    return { hostContext: app.getHostContext() };
  },
  callTool: (name, args) => app.callServerTool({ name, arguments: args }),
  openLink: (url) => app.openLink({ url }),
  updateModelContext: (text) => app.updateModelContext({ content: [{ type: "text", text }] }),
  requestDisplayMode: (mode) => app.requestDisplayMode({ mode }),
  host: () => ({ capabilities: app.getHostCapabilities() ?? {}, context: app.getHostContext() ?? {} }),
  message: (text) => app.sendMessage({ role: "user", content: [{ type: "text", text }] }),
};
