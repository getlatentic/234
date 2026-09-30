// SPDX-License-Identifier: AGPL-3.0-or-later
// The host's half of the MCP Apps handshake and lifecycle in the real chat page, behind the sandbox proxy, checked
// against what the official ext-apps AppBridge (the oracle: it is the host here) and App send and accept: the order of
// messages, the initialize result (protocol version, host capabilities, host context), the notifications the host
// sends when the theme, the display mode or the frame changes, teardown, and what the host ignores.
//
// needs the stack. usage: PORT_BASE=8920 node conformance/chat-bridge.mjs
import { browser, freshLedger, cardFrames, cardIn, pause, startChat, suite, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Chat host, MCP Apps lifecycle");
await freshLedger();
const chromium = await browser();
const errors = [];
const context = await chromium.newContext({ viewport: { width: 420, height: 800 }, colorScheme: "light" });
const page = await context.newPage();
watchErrors(page, errors);

// What each frame hears, in order, from whom (a cross-origin window's postMessage cannot be watched from outside, so
// the proxy's own timeline stands for what the host sent and what the card said).
await page.addInitScript(() => {
  window.__wire = [];
  addEventListener(
    "message",
    (event) => {
      if (!event.data || typeof event.data !== "object") return;
      const from = event.source === window.parent ? "parent" : event.source === window ? "self" : "child";
      window.__wire.push({ from, origin: event.origin, data: JSON.parse(JSON.stringify(event.data)) });
    },
    true,
  );
});
const proxy = () => page.frames().find((f) => new URL(f.url()).pathname === "/" && f.url().includes("host="));
const heard = (frame) => frame.evaluate(() => window.__wire);
const relayed = [];
page.on("request", (request) => request.url().endsWith("/call") && relayed.push(request.postData()));

await startChat(page, "Pay ₦2,500 to Demo Kitchen for lunch");
const card = cardIn(page);
await card.getByRole("button", { name: /Approve/ }).waitFor({ timeout: 20000 });
await pause(500);

console.log("order of messages");
const timeline = await heard(proxy());
const fromHost = timeline.filter((m) => m.from === "parent");
const kind = (m) => m.data.method ?? (m.data.result ? "response" : "?");
check(timeline[0].from === "child" || timeline[0].from === "parent", "the proxy has a timeline");
check(fromHost[0].data.method === "ui/notifications/sandbox-resource-ready" && typeof fromHost[0].data.params.html === "string" && fromHost[0].data.params.html.includes("<html"), "the first thing the host sends is the card's raw HTML in sandbox-resource-ready");
check(fromHost.every((m) => m.origin === new URL(page.url()).origin), "and everything the proxy hears from the host comes from the host's origin");
const initialised = timeline.findIndex((m) => m.from === "child" && m.data.method === "ui/notifications/initialized");
const before = timeline.slice(0, initialised).filter((m) => m.from === "parent").slice(1);
check(initialised > 0 && before.length === 1 && kind(before[0]) === "response", `before the card's initialized notification the host sends it only the initialize response (${before.map(kind).join(", ")})`);
const after = timeline.slice(initialised + 1).filter((m) => m.from === "parent").map(kind);
check(after[0] === "ui/notifications/tool-input" && after.includes("ui/notifications/tool-result") && after.indexOf("ui/notifications/tool-input") < after.indexOf("ui/notifications/tool-result"), `then tool-input, then tool-result (${after.slice(0, 3).join(", ")})`);
check(!after.includes("ui/notifications/tool-input-partial") && !after.includes("ui/notifications/tool-cancelled"), "tool-input-partial and tool-cancelled are not sent for a call that ran to its result");
const ask = timeline.find((m) => m.from === "child" && m.data.method === "ui/initialize");
check(ask.data.params.protocolVersion && ask.data.params.appInfo && ask.data.params.appCapabilities !== undefined, "the card's ui/initialize carries protocolVersion, appInfo and appCapabilities");

console.log("the initialize result");
const init = fromHost.find((m) => m.data.result?.hostCapabilities).data.result;
check(init.protocolVersion === "2026-01-26", `protocolVersion is the standard's (${init.protocolVersion})`);
check(init.hostInfo?.name === "checkout-host", "hostInfo names the host");
const capabilities = init.hostCapabilities;
check(capabilities.openLinks && capabilities.serverTools && capabilities.logging && capabilities.updateModelContext?.text && capabilities.message?.text, "hostCapabilities lists what the host does: open links, server tools, logging, model context, messages");
check(JSON.stringify(capabilities.sandbox?.permissions) === "{}", "sandbox.permissions is empty: no browser feature is granted to a card");
check(JSON.stringify(Object.entries(capabilities.sandbox?.csp ?? {}).sort()) === JSON.stringify([["frameDomains", ["https://checkout.paystack.com"]], ["resourceDomains", ["https://js.paystack.co"]]]), "sandbox.csp is the origins the host approves");
check(!("serverResources" in capabilities) && !("downloadFile" in capabilities) && !("sampling" in capabilities), "and it does not claim resource reads, downloads or sampling, which it does not do");
const context_ = init.hostContext;
const keys = Object.keys(context_).sort();
check(["availableDisplayModes", "containerDimensions", "deviceCapabilities", "displayMode", "locale", "platform", "safeAreaInsets", "styles", "theme", "timeZone", "userAgent"].every((k) => keys.includes(k)), `hostContext carries ${keys.join(", ")}`);
check(context_.theme === "light" && context_.platform === "web" && context_.displayMode === "inline" && JSON.stringify(context_.availableDisplayModes) === '["inline","fullscreen"]', "theme, platform, display mode and the modes on offer");
check(typeof context_.locale === "string" && typeof context_.timeZone === "string" && typeof context_.deviceCapabilities.touch === "boolean" && typeof context_.deviceCapabilities.hover === "boolean", "locale, time zone and device capabilities");
check(context_.containerDimensions.maxHeight > 0 && context_.containerDimensions.width > 0 && Object.keys(context_.safeAreaInsets).join() === "top,right,bottom,left", "container dimensions (flexible height, fixed width) and safe area insets");
const variables = context_.styles.variables;
check(variables["--color-text-primary"].startsWith("light-dark(") && variables["--font-sans"] && variables["--border-radius-md"] && variables["--shadow-md"], "styles.variables carries colours as light-dark(), type, radii and shadows in the standard's names");
const view = () => cardFrames(page)[0];
check((await view().evaluate(() => McpApp.host().capabilities.sandbox.csp.frameDomains[0])) === "https://checkout.paystack.com", "the card read the same capabilities through its client");

console.log("the host tells the card when its context changes");
const count = (await heard(proxy())).length;
await page.emulateMedia({ colorScheme: "dark" });
await pause(700);
const changed = (await heard(proxy())).slice(count).filter((m) => m.from === "parent" && m.data.method === "ui/notifications/host-context-changed");
check(changed.length >= 1 && changed.some((m) => m.data.params.theme === "dark"), "a change of theme is sent as host-context-changed, with the new theme");
check((await view().evaluate(() => McpApp.host().context.theme)) === "dark", "and the card has it");
await page.emulateMedia({ colorScheme: "light" });

console.log("display modes");
const mode = (m) => view().evaluate((wanted) => McpApp.requestDisplayMode(wanted), m);
const fullCount = (await heard(proxy())).length;
check((await mode("fullscreen")).mode === "fullscreen", "ui/request-display-mode fullscreen is granted, and the result says so");
await pause(400);
const fullscreen = (await heard(proxy())).slice(fullCount).filter((m) => m.from === "parent" && m.data.method === "ui/notifications/host-context-changed");
check(fullscreen.some((m) => m.data.params.displayMode === "fullscreen" && "height" in (m.data.params.containerDimensions ?? {})), "the card is told: fullscreen, with a fixed height now");
check((await mode("pip")).mode === "fullscreen", "a mode the host does not offer (pip) gets the current mode back");
check((await mode("inline")).mode === "inline", "ui/request-display-mode inline gives the card back its place");
await pause(400);
check((await view().evaluate(() => McpApp.host().context.availableDisplayModes)).includes("fullscreen"), "the modes on offer are still listed after a change (the bridge replaces the context, so the host resends it whole)");

console.log("what the host ignores");
const beforeSpoof = relayed.length;
await page.evaluate(() => {
  const rogue = document.createElement("iframe");
  rogue.setAttribute("sandbox", "allow-scripts");
  rogue.srcdoc = `<script>parent.postMessage({ jsonrpc: "2.0", id: 99, method: "tools/call", params: { name: "approve_quote", arguments: { quote_id: "x" } } }, "*");parent.postMessage({ jsonrpc: "2.0", method: "ui/notifications/sandbox-proxy-ready" }, "*");<\/script>`;
  document.body.append(rogue);
});
await pause(800);
const answeredRogue = (await heard(proxy())).some((m) => m.data.id === 99);
check(relayed.length === beforeSpoof && !answeredRogue, "a window that is not the proxy cannot make the host call a tool or answer it");

console.log("teardown");
const tornCount = (await heard(proxy())).length;
await page.evaluate(() => dispatchEvent(new Event("pagehide")));
await pause(600);
const tail = (await heard(proxy())).slice(tornCount);
const teardown = tail.find((m) => m.from === "parent" && m.data.method === "ui/resource-teardown");
check(Boolean(teardown) && teardown.data.id !== undefined, "before the page goes, ui/resource-teardown is sent to the card as a request");
check(tail.some((m) => m.from === "child" && m.data.id === teardown?.data.id && "result" in m.data), "and the card answers it");

const unexpected = errors.filter((e) => !/allow-scripts and allow-same-origin|Failed to load resource|Content Security Policy|Blocked script execution|about:srcdoc/.test(e));
check(unexpected.length === 0, `no page errors ${unexpected.join("; ")}`);
await context.close();
await chromium.close();
finish();
