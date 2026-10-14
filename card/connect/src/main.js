// SPDX-License-Identifier: AGPL-3.0-or-later
// The connect card: the person connects their own account for a merchant, or ends the connection. They sign in at
// Paystack Index on Index's own page (the card opens the link and asks 234 how it stands), and for Chowdeck they
// type the phone number of their Chowdeck account and the code texted to it into this card. The phone and the
// code go from here to the server and nowhere else: not to the chat, not to the model. The card never holds a
// token, only what the server says about the connection.
const POLL_MS = 3000;
const root = document.getElementById("root");
const state = { id: null, view: null, link: null, phone: "", back: false, busy: false, notice: "", timer: null, told: false, seen: null };

const fromTemplate = (id) => document.getElementById(id).content.firstElementChild.cloneNode(true);
const slot = (node, name) => node.querySelector(`[data-slot="${name}"]`);
const show = (node, on) => node.toggleAttribute("hidden", !on);
const plain = (text) => (text ?? "").replace(/^[A-Z][A-Z_]+:\s*/, "");
const textOf = (result) => result.content?.find((block) => block.type === "text")?.text;

// What each state says and offers. A step is a title, a line under it, the field it asks for, and its buttons.
const STEPS = {
  authorize: (v) => ({ title: `Connect your ${v.provider} account`, lead: v.merchant ? `To use ${v.merchant}. You sign in at Index; 234 never sees your password.` : "You sign in at Index; 234 never sees your password.", actions: [["open", "Connect Paystack Index", "btn-primary"]] }),
  phone: (v) => ({ title: `Link ${v.merchant ?? "the merchant"}`, lead: "Index texts a code to the phone number of your account there.", field: ["Phone number", "tel", "send"], actions: [["send", "Send code", "btn-primary"]] }),
  code: () => ({ title: "Enter the code", lead: "It was texted to the number you gave.", field: ["Code", "text", "confirm"], actions: [["confirm", "Confirm", "btn-primary"], ["again", "Use another number", "btn-quiet"]] }),
  connected: (v) => ({ title: `${v.provider} connected`, status: ["ok", v.merchant ? `${v.merchant} is ready to use` : "Ready to use"], actions: [["disconnect", "Disconnect", "btn-quiet"]] }),
  expired: (v) => ({ title: `Connect your ${v.provider} account`, status: ["off", "The sign-in ran out"], actions: [["restart", "Try again", "btn-primary"]] }),
  denied: (v) => ({ title: `Connect your ${v.provider} account`, status: ["off", "Nothing was connected"], actions: [["restart", "Try again", "btn-primary"]] }),
  disconnected: (v) => ({ title: `${v.provider} disconnected`, status: ["off", "Disconnected"], lead: v.notice ?? "" }),
};

function stepOf(view) {
  return STEPS[state.back && view.state === "code" ? "phone" : view.state](view);
}

function draw() {
  const view = state.view;
  const step = stepOf(view);
  const card = fromTemplate("t-card");
  slot(card, "title").textContent = step.title;
  slot(card, "lead").textContent = step.lead ?? "";
  show(slot(card, "lead"), Boolean(step.lead));
  if (step.status) {
    slot(card, "status-text").textContent = step.status[1];
    show(slot(card, step.status[0]), true);
    show(slot(card, "status"), true);
  }
  if (step.field) {
    const entry = slot(card, "entry");
    slot(card, "field-label").textContent = step.field[0];
    entry.type = step.field[1];
    entry.inputMode = step.field[1] === "tel" ? "tel" : "text";
    entry.dataset.enter = step.field[2];
    show(slot(card, "fields"), true);
  }
  for (const [action, label, style] of step.actions ?? []) {
    const button = fromTemplate("t-button");
    button.textContent = label;
    button.className = style;
    button.dataset.action = action;
    slot(card, "actions").append(button);
  }
  slot(card, "notice").textContent = state.notice;
  show(slot(card, "notice"), Boolean(state.notice));
  root.replaceChildren(card);
  root.querySelectorAll("button, input").forEach((node) => { node.disabled = state.busy; });
  root.querySelector('[data-slot="entry"]')?.focus();
}

function schedule() {
  clearTimeout(state.timer);
  if (state.view?.state === "authorize") state.timer = setTimeout(() => call("connection_status"), POLL_MS);
}

function notice(text) {
  const card = fromTemplate("t-message");
  card.textContent = text;
  root.replaceChildren(card);
}

// The model hears once that the person finished, and only for a connection this card saw happen.
function tellModel(before) {
  if (state.view.state !== "connected" || state.told || !before || before === "connected") return;
  state.told = true;
  const what = state.view.merchant ? `${state.view.provider} and linked ${state.view.merchant}` : state.view.provider;
  McpApp.message(`I've connected ${what}.`).catch(() => undefined);
}

function apply(result) {
  if (result.isError) {
    state.notice = plain(textOf(result)) || "The request was refused.";
    return state.view ? draw() : notice(state.notice);
  }
  const data = result.structuredContent ?? {};
  if (!data.connection || !data.card_id) return notice("The server sent a reply this card cannot show.");
  const before = state.view?.state;
  state.id = data.card_id;
  state.view = data.connection;
  state.link = data.connection.link ?? (state.view.state === "authorize" ? state.link : null);
  state.notice = data.connection.notice && state.view.state !== "disconnected" ? data.connection.notice : "";
  if (state.view.state !== "code") state.back = false;
  draw();
  schedule();
  tellModel(before);
}

async function call(tool, args = {}) {
  state.busy = true;
  try {
    apply(await McpApp.callTool(tool, { card_id: state.id, ...args }));
  } catch {
    state.notice = "The connection to the server was lost. Try again.";
    if (state.view) draw();
  } finally {
    state.busy = false;
    if (state.view) draw();
    schedule();
  }
}

const entered = () => root.querySelector('[data-slot="entry"]')?.value.trim() ?? "";

const ACTIONS = {
  open: () => state.link && McpApp.openLink(state.link).catch(() => window.open(state.link, "_blank", "noopener")),
  restart: () => call("restart_connection"),
  disconnect: () => call("disconnect_account"),
  again: () => { state.back = true; state.notice = ""; draw(); },
  send: () => { state.phone = entered(); state.back = false; return state.phone && call("send_link_code", { phone: state.phone }); },
  confirm: () => entered() && call("confirm_link_code", { phone: state.phone, code: entered() }),
};

root.addEventListener("click", (event) => {
  const name = event.target.closest("[data-action]")?.dataset.action;
  if (name && ACTIONS[name]) ACTIONS[name]();
});
// A sandboxed view may not submit forms, so the phone and the code are sent by the button or by Enter.
root.addEventListener("keydown", (event) => {
  const name = event.target.dataset?.enter;
  if (event.key === "Enter" && name && ACTIONS[name]) ACTIONS[name]();
});

McpApp.on("ui/notifications/tool-result", apply);
McpApp.on("ui/notifications/tool-input", () => undefined);
McpApp.on("ui/notifications/tool-cancelled", () => notice("The request was cancelled."));
McpApp.on("ui/resource-teardown", () => {
  clearTimeout(state.timer);
  return {};
});
const hostContext = (context) => {
  if (context?.theme) for (const theme of ["dark", "light"]) document.documentElement.classList.toggle(theme, context.theme === theme);
};
McpApp.on("ui/notifications/host-context-changed", hostContext);
hostContext({ theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light" });

McpApp.connect({ name: "connect", title: "Connect an account", version: "0.1.0" }).then(
  (hello) => hostContext(hello.hostContext),
  (error) => {
    root.textContent = `Could not connect to the chat: ${error.message}`;
  },
);
