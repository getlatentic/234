// SPDX-License-Identifier: AGPL-3.0-or-later
// The two scripts the sandbox serves. Each is written as a function and served as its source text, so it is
// ordinary JavaScript that is linted and read, and the hash the proxy page's policy names is the hash of
// exactly what is served.

/** Runs in the proxy page: the outer frame, which the host embeds and which frames the view. */
export function proxyMain() {
  const READY = "ui/notifications/sandbox-proxy-ready";
  const RESOURCE_READY = "ui/notifications/sandbox-resource-ready";
  const INNER_HTML = "ui/notifications/sandbox-inner-html";
  const RESERVED = "ui/notifications/sandbox-";
  const HOST = document.querySelector('meta[name="host-origin"]').content;
  const PERMISSIONS = { camera: "camera", microphone: "microphone", geolocation: "geolocation", clipboardWrite: "clipboard-write" };
  const SANDBOX_FLAGS = ["allow-scripts", "allow-same-origin", "allow-forms", "allow-popups", "allow-modals"];
  let view = null;
  let viewOrigin = "null";

  const isRpc = (data) => data !== null && typeof data === "object" && data.jsonrpc === "2.0";
  const isReserved = (data) => typeof data.method === "string" && data.method.startsWith(RESERVED);

  // A proxy that can reach the top page, or is the top page, is not sandboxed: refuse to run.
  const cross = (() => {
    try {
      void window.top.document;
      return false;
    } catch {
      return true;
    }
  })();
  if (window.parent === window || !cross) return;

  // A view has no origin of its own unless the host asks for allow-same-origin, which puts it on this origin.
  const sandboxFlags = (requested) => {
    const flags = typeof requested === "string" ? requested.split(/\s+/).filter((flag) => SANDBOX_FLAGS.includes(flag)) : [];
    return flags.includes("allow-scripts") ? flags.join(" ") : "allow-scripts";
  };
  const allowList = (granted) =>
    Object.entries(PERMISSIONS)
      .filter(([name]) => granted && typeof granted === "object" && granted[name] !== undefined)
      .map(([, feature]) => feature)
      .join("; ");

  function load({ html, sandbox, csp, permissions, signature }) {
    if (typeof html !== "string" || view) return;
    const frame = document.createElement("iframe");
    const flags = sandboxFlags(sandbox);
    frame.setAttribute("sandbox", flags);
    viewOrigin = flags.split(" ").includes("allow-same-origin") ? location.origin : "null";
    const allow = allowList(permissions);
    if (allow) frame.setAttribute("allow", allow);
    const address = new URL("/view", location.href);
    address.searchParams.set("host", HOST);
    if (csp !== undefined && csp !== null) address.searchParams.set("csp", JSON.stringify(csp));
    if (typeof signature === "string") address.searchParams.set("sig", signature);
    frame.addEventListener(
      "load",
      () => frame.contentWindow.postMessage({ jsonrpc: "2.0", method: INNER_HTML, params: { html } }, "*"),
      { once: true },
    );
    frame.src = address.href;
    view = frame;
    document.body.append(frame);
  }

  window.addEventListener("message", (event) => {
    const data = event.data;
    if (event.source === window.parent) {
      if (event.origin !== HOST || !isRpc(data)) return;
      if (data.method === RESOURCE_READY) load(data.params ?? {});
      else if (!isReserved(data) && view) view.contentWindow.postMessage(data, "*");
    } else if (view && event.source === view.contentWindow) {
      if (event.origin !== viewOrigin || !isRpc(data) || isReserved(data)) return;
      window.parent.postMessage(data, HOST);
    }
  });

  window.parent.postMessage({ jsonrpc: "2.0", method: READY, params: {} }, HOST);
}

/** Runs in the view's own document before the view: takes the view's HTML from the proxy and writes it in. */
export function innerMain() {
  const INNER_HTML = "ui/notifications/sandbox-inner-html";
  const take = (event) => {
    const message = event.data;
    if (event.source !== window.parent || !message || message.method !== INNER_HTML) return;
    if (typeof message.params?.html !== "string") return;
    window.removeEventListener("message", take);
    document.open();
    document.write(message.params.html);
    document.close();
  };
  window.addEventListener("message", take);
}

export const iife = (fn) => `(${fn.toString()})();`;
