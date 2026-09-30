// SPDX-License-Identifier: AGPL-3.0-or-later
// A stand-in for Paystack's popup script and checkout page, served at Paystack's own origins by the browser context
// (so the page's real Content-Security-Policy decides what may load, exactly as with the real thing). `PaystackPop`
// here does what Inline v2 does that the card relies on: `resumeTransaction(code, { onLoad, onSuccess, onCancel,
// onError })` puts a full-window frame of checkout.paystack.com in the page and reports when it has loaded.
// A test drives the payment through `window.__paystack`.

const SCRIPT = `
window.__paystack = { opened: 0, codes: [], popups: [] };
window.PaystackPop = class PaystackPop {
  resumeTransaction(code, callbacks) {
    window.__paystack.opened += 1;
    window.__paystack.codes.push(code);
    window.__paystack.popups.push(this);
    this.callbacks = callbacks;
    const frame = document.createElement("iframe");
    frame.src = "https://checkout.paystack.com/popup?stub=1";
    frame.title = "Paystack checkout (stub)";
    frame.style.cssText = "position:fixed;inset:0;width:100%;height:100%;border:0;background:#fff";
    frame.addEventListener("load", () => __MODE__);
    document.body.append(frame);
    this.frame = frame;
  }
  cancelTransaction() { this.frame?.remove(); this.callbacks.onCancel?.(); }
  close() { this.frame?.remove(); }
};
`;

const MODES = {
  works: `callbacks.onLoad?.({ id: 1, accessCode: code })`,
  "errors-on-load": `callbacks.onError?.({ message: "setup failed" })`,
  "never-loads": `undefined`,
  slow: `setTimeout(() => callbacks.onLoad?.({ id: 1, accessCode: code }), 3000)`,
};

const CHECKOUT = "<!doctype html><meta charset=utf-8><title>Paystack checkout (stub)</title><body style='font:16px system-ui'>Paystack checkout (stub)";

export const scriptFor = (mode) => SCRIPT.replace("__MODE__", MODES[mode] ?? MODES.works);

/**
 * Serves the stub for js.paystack.co and checkout.paystack.com in a browser context. `script` is `works`,
 * `errors-on-load`, `slow` (loads after 3 s) or `never-loads`, or `missing` (the script request fails), `violates` (the script tries an
 * undeclared origin first), `slow-error` (a script that throws).
 */
export async function paystackStub(context, { script = "works", requests = [] } = {}) {
  await context.route("https://js.paystack.co/**", (route) => {
    requests.push(route.request().url());
    if (script === "missing") return route.abort();
    if (script === "violates") {
      const body = `document.head.append(Object.assign(document.createElement("script"), { src: "https://undeclared.example/x.js" }));${scriptFor("works")}`;
      return route.fulfill({ contentType: "text/javascript", body });
    }
    if (script === "throws") return route.fulfill({ contentType: "text/javascript", body: "throw new Error('stub')" });
    return route.fulfill({ contentType: "text/javascript", body: scriptFor(script) });
  });
  await context.route("https://checkout.paystack.com/**", (route) => {
    requests.push(route.request().url());
    return route.fulfill({ contentType: "text/html", body: CHECKOUT });
  });
  return requests;
}
