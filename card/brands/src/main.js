// SPDX-License-Identifier: AGPL-3.0-or-later
// The sign-in card: a Brand needs the person's permission before 234 can act on their account there. The card
// opens the Brand's own sign-in page, where the Brand shows what it asks for; it asks 234 how the sign-in
// stands at the Brand's pace, and when the Brand has issued the token it says so in the chat once, so the
// request can be sent again. The card never sees a token.
const root = document.getElementById("root");
const state = { id: null, view: null, timer: null, told: false };

const fromTemplate = (id) => document.getElementById(id).content.firstElementChild.cloneNode(true);
const slot = (node, name) => node.querySelector(`[data-slot="${name}"]`);
const textOf = (result) => result.content?.find((block) => block.type === "text")?.text;

const ENDED = {
  connected: { text: (v) => `Connected to ${v.brand}`, glyph: "ok" },
  denied: { text: (v) => `Not allowed at ${v.brand}`, glyph: "off" },
  expired: { text: () => "The sign-in expired", glyph: "off" },
};

function drawAsk(view) {
  const card = fromTemplate("t-ask");
  slot(card, "title").textContent = `${view.brand} needs your permission`;
  card.querySelector('[data-action="sign-in"]').textContent = `Sign in with ${view.brand}`;
  return card;
}

function drawDone(view) {
  const ended = ENDED[view.state] ?? ENDED.expired;
  const card = fromTemplate("t-done");
  slot(card, "status").textContent = ended.text(view);
  slot(card, ended.glyph).hidden = false;
  return card;
}

function notice(text) {
  const card = fromTemplate("t-notice");
  card.textContent = text;
  root.replaceChildren(card);
}

function schedule(seconds) {
  clearTimeout(state.timer);
  state.timer = setTimeout(ask, Math.max(seconds, 5) * 1000);
}

// What a result means to this card: a sign-in to show, and whether to keep asking about it.
function apply(result) {
  if (result.isError) return notice(textOf(result) ?? "The sign-in could not be shown.");
  const data = result.structuredContent ?? {};
  if (!data.sign_in || !data.card_id) return notice("The server sent a reply this card cannot show.");
  state.id = data.card_id;
  state.view = data.sign_in;
  root.replaceChildren(state.view.state === "pending" ? drawAsk(state.view) : drawDone(state.view));
  if (state.view.state === "pending") schedule(state.view.interval ?? 5);
  else clearTimeout(state.timer);
  if (data.connected_now && !state.told) {
    state.told = true;
    McpApp.message(`I've signed in with ${state.view.brand}.`).catch(() => undefined);
  }
}

async function ask() {
  try {
    apply(await McpApp.callTool("sign_in_status", { card_id: state.id }));
  } catch {
    schedule(10);
  }
}

root.addEventListener("click", (event) => {
  if (event.target.closest('[data-action="sign-in"]') && state.view?.link) McpApp.openLink(state.view.link).catch(() => window.open(state.view.link, "_blank", "noopener"));
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

McpApp.connect({ name: "brands", title: "Sign in at a Brand", version: "0.1.0" }).then(
  (hello) => hostContext(hello.hostContext),
  (error) => {
    root.textContent = `Could not connect to the chat: ${error.message}`;
  },
);
