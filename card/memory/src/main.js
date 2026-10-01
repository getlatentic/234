// SPDX-License-Identifier: AGPL-3.0-or-later
// The memory card: what 234 proposes to remember, with Save and No, then what became of it; or what it forgot,
// with Undo. The card draws what the server sent and calls three tools with the token it was given. It saves
// nothing itself, and the model never has the token.
const root = document.getElementById("root");
const state = { id: null, token: null, view: null, busy: false, notice: "" };

const fromTemplate = (id) => document.getElementById(id).content.firstElementChild.cloneNode(true);
const slot = (node, name) => node.querySelector(`[data-slot="${name}"]`);
const show = (node, on) => {
  node.hidden = !on;
};
const plainError = (text) => (text ?? "").replace(/^[A-Z][A-Z_]+:\s*/, "");
const textOf = (result) => result.content?.find((block) => block.type === "text")?.text;

const CAPTIONS = { recipient: "Save recipient", preference: "Remember", fact: "Remember" };
const DONE = {
  saved: { text: (v) => `Saved: ${v.title}`, glyph: "ok" },
  discarded: { text: () => "Not saved", glyph: "off" },
  expired: { text: () => "Expired", glyph: "off" },
  refused: { text: (v) => v.note || "Not saved", glyph: "off" },
  forgotten: { text: (v) => `Forgot: ${v.title}`, glyph: "off", undo: true },
  restored: { text: (v) => `Restored: ${v.title}`, glyph: "ok" },
};

function drawAsk(view) {
  const card = fromTemplate("t-ask");
  setText(card, "caption", view.op === "update" ? "Change" : CAPTIONS[view.kind]);
  setText(card, "what", view.what);
  setText(card, "detail", view.detail);
  setText(card, "notice", state.notice);
  return card;
}

function drawDone(view) {
  const done = DONE[view.state];
  const card = fromTemplate("t-done");
  setText(card, "status", done.text(view));
  show(slot(card, done.glyph), true);
  show(card.querySelector('[data-action="undo"]'), Boolean(done.undo));
  return card;
}

function setText(node, name, text) {
  const target = slot(node, name);
  target.textContent = text ?? "";
  show(target, Boolean(text));
}

function draw() {
  const view = state.view;
  root.replaceChildren(view.state === "pending" ? drawAsk(view) : drawDone(view));
  syncBusy();
}

function syncBusy() {
  root.querySelectorAll("button").forEach((button) => {
    button.disabled = state.busy;
  });
}

function showNotice(text) {
  state.notice = plainError(text) || "The request was refused.";
  if (state.view) return draw();
  const notice = fromTemplate("t-notice");
  notice.textContent = state.notice;
  root.replaceChildren(notice);
}

// What a tool result means to this card: a proposal or a decision to show, or the reason there is none.
function apply(result) {
  if (result.isError) return showNotice(textOf(result));
  const memory = result.structuredContent?.memory;
  if (!memory) return showNotice("The server sent a reply this card cannot show.");
  if (result._meta?.confirmToken) state.token = result._meta.confirmToken;
  state.id = result.structuredContent.proposal_id;
  state.view = memory;
  state.notice = "";
  draw();
}

async function decide(tool) {
  state.busy = true;
  syncBusy();
  try {
    apply(await McpApp.callTool(tool, { proposal_id: state.id, confirm_token: state.token ?? "" }));
  } catch {
    showNotice("The connection to the server was lost. Try again.");
  } finally {
    state.busy = false;
    if (state.view) syncBusy();
  }
}

const actions = { save: () => decide("confirm_memory"), no: () => decide("discard_memory"), undo: () => decide("undo_memory") };

root.addEventListener("click", (event) => {
  const name = event.target.closest("button[data-action]")?.dataset.action;
  if (name && state.view) actions[name]?.();
});

McpApp.on("ui/notifications/tool-result", apply);
McpApp.on("ui/notifications/tool-input", () => undefined);
McpApp.on("ui/notifications/tool-cancelled", () => showNotice("The request was cancelled."));
McpApp.on("ui/resource-teardown", () => ({}));
const hostContext = (context) => {
  if (context?.theme) for (const theme of ["dark", "light"]) document.documentElement.classList.toggle(theme, context.theme === theme);
};
McpApp.on("ui/notifications/host-context-changed", hostContext);
hostContext({ theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light" });

McpApp.connect({ name: "memory", title: "Memory", version: "0.1.0" }).then(
  (hello) => hostContext(hello.hostContext),
  (error) => {
    root.textContent = `Could not connect to the chat: ${error.message}`;
  },
);
