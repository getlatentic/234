// SPDX-License-Identifier: AGPL-3.0-or-later
// A minimal MCP Apps view: JSON-RPC 2.0 over window.postMessage to the host that framed us.
// Wire format: ext-apps specification 2026-01-26 (ui/initialize, ui/notifications/*, tools/call).
const McpApp = (() => {
  const PROTOCOL_VERSION = "2026-01-26";
  const pending = new Map();
  const handlers = new Map();
  let nextId = 1;
  let host = { capabilities: {}, context: {} };

  // The host's origin is not known to a sandboxed view, so "*" is the only target; the source
  // check on the way in is what identifies the host.
  const post = (message) => window.parent.postMessage({ jsonrpc: "2.0", ...message }, "*");

  const request = (method, params) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      post({ id, method, params });
    });

  const notify = (method, params) => post({ method, params });

  const on = (method, handler) => handlers.set(method, handler);

  function answer(id, work) {
    Promise.resolve()
      .then(work)
      .then(
        (result) => post({ id, result: result ?? {} }),
        (error) => post({ id, error: { code: -32603, message: String(error?.message ?? error) } }),
      );
  }

  function receive(message) {
    if (message.method === "ui/notifications/host-context-changed") host.context = { ...host.context, ...message.params };
    if (typeof message.method === "string") {
      const handler = handlers.get(message.method);
      if (message.id === undefined) return handler?.(message.params);
      if (!handler) return post({ id: message.id, error: { code: -32601, message: `Method not found: ${message.method}` } });
      return answer(message.id, () => handler(message.params));
    }
    const waiting = pending.get(message.id);
    if (!waiting) return;
    pending.delete(message.id);
    if (message.error) waiting.reject(new Error(message.error.message));
    else waiting.resolve(message.result);
  }

  window.addEventListener("message", (event) => {
    const message = event.data;
    if (event.source !== window.parent || !message || message.jsonrpc !== "2.0") return;
    receive(message);
  });

  // Tells the host how tall the document is, whenever that changes.
  function reportSize() {
    let queued = false;
    let last = "";
    const measure = () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        const root = document.documentElement;
        const previous = root.style.height;
        root.style.height = "max-content";
        const height = Math.ceil(root.getBoundingClientRect().height);
        root.style.height = previous;
        const width = Math.ceil(window.innerWidth);
        if (`${width}x${height}` === last) return;
        last = `${width}x${height}`;
        notify("ui/notifications/size-changed", { width, height });
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(document.documentElement);
    observer.observe(document.body);
  }

  async function connect(appInfo, appCapabilities = {}) {
    const hello = await request("ui/initialize", { appInfo, appCapabilities, protocolVersion: PROTOCOL_VERSION });
    host = { capabilities: hello.hostCapabilities ?? {}, context: hello.hostContext ?? {} };
    notify("ui/notifications/initialized");
    reportSize();
    return hello;
  }

  return {
    connect,
    on,
    callTool: (name, args) => request("tools/call", { name, arguments: args }),
    openLink: (url) => request("ui/open-link", { url }),
    requestDisplayMode: (mode) => request("ui/request-display-mode", { mode }),
    host: () => host,
    updateModelContext: (text) => request("ui/update-model-context", { content: [{ type: "text", text }] }),
  };
})();
