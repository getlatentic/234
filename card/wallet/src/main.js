// SPDX-License-Identifier: AGPL-3.0-or-later
// The wallet card: the balance and the latest entries as the server holds them, and Add money, which asks the
// server for a checkout and opens it. Money arrives only through the checkout's webhook; the card then reads the
// wallet again until it shows.
const POLL_MS = 3000;
const POLL_FOR_MS = 30 * 60 * 1000;
const MIN_NAIRA = 100;
const root = document.getElementById("root");
const state = { cardId: null, wallet: null, topup: null, busy: false, notice: "", amount: "", until: 0 };

const fromTemplate = (id) => document.getElementById(id).content.firstElementChild.cloneNode(true);
const slot = (node, name) => node.querySelector(`[data-slot="${name}"]`);
const show = (node, on) => node.toggleAttribute("hidden", !on);
const plainError = (text) => (text ?? "").replace(/^[A-Z][A-Z_]+:\s*/, "");
const textOf = (result) => result.content?.find((block) => block.type === "text")?.text;

function setText(node, name, text) {
  const target = slot(node, name);
  target.textContent = text ?? "";
  show(target, Boolean(text));
}

function entryOf(entry) {
  const line = fromTemplate("t-entry");
  slot(line, "label").textContent = entry.label;
  slot(line, "amount").textContent = entry.amount;
  return line;
}

function draw() {
  const card = fromTemplate("t-wallet");
  setText(card, "balance", state.wallet.balance);
  slot(card, "entries").replaceChildren(...state.wallet.entries.map(entryOf));
  slot(card, "amount").value = state.amount;
  setText(card, "pay", state.topup ? `Pay ${state.topup.amount}` : "");
  setText(card, "notice", state.notice);
  const focused = document.activeElement?.dataset?.slot;
  root.replaceChildren(card);
  if (focused === "amount") slot(card, "amount").focus();
  syncBusy();
}

function syncBusy() {
  root.querySelectorAll("button, input").forEach((control) => {
    control.disabled = state.busy;
  });
}

function showNotice(text) {
  state.notice = plainError(text) || "The request was refused.";
  if (state.wallet) return draw();
  const notice = fromTemplate("t-notice");
  notice.textContent = state.notice;
  root.replaceChildren(notice);
}

// A result names its card and carries the wallet as it stands; a top-up also carries its checkout.
function apply(result) {
  if (result.isError) return showNotice(textOf(result));
  const data = result.structuredContent;
  if (!data?.wallet || !data.card_id) return showNotice("The server sent a reply this card cannot show.");
  const arrived = state.topup && data.wallet.balanceKobo > state.wallet.balanceKobo;
  state.cardId = data.card_id;
  state.wallet = data.wallet;
  if (data.topup) state.topup = data.topup;
  if (arrived) state.topup = null;
  state.notice = "";
  draw();
}

async function call(tool, args) {
  try {
    apply(await McpApp.callTool(tool, { card_id: state.cardId, ...args }));
  } catch {
    showNotice("The connection to the server was lost. Try again.");
  }
}

async function act(work) {
  state.busy = true;
  syncBusy();
  try {
    await work();
  } finally {
    state.busy = false;
    syncBusy();
  }
}

const openPayment = () =>
  McpApp.openLink(state.topup.checkoutUrl).then(
    (answer) => answer?.isError !== true || showNotice("The payment window was blocked. Press Pay again."),
    () => showNotice("The payment window was blocked. Press Pay again."),
  );

async function addMoney() {
  state.amount = slot(root, "amount").value.replace(/[\s,₦]/g, "");
  const naira = Number(state.amount);
  if (!Number.isInteger(naira) || naira < MIN_NAIRA) return showNotice(`Enter at least ₦${MIN_NAIRA}.`);
  await act(() => call("start_topup", { amount_naira: naira }));
  if (!state.topup?.checkoutUrl || state.notice) return;
  state.amount = "";
  state.until = Date.now() + POLL_FOR_MS;
  draw();
  await openPayment();
}

const actions = { add: addMoney, pay: () => state.topup && openPayment() };

root.addEventListener("click", (event) => {
  const name = event.target.closest("button[data-action]")?.dataset.action;
  if (name && state.wallet && !state.busy) actions[name]?.();
});
root.addEventListener("input", (event) => {
  if (event.target.dataset.slot === "amount") state.amount = event.target.value;
});
// A sandboxed view may not submit forms, so the amount goes by the button or by Enter in its field.
root.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.target.dataset.slot === "amount" && !state.busy) addMoney();
});

let polling = false;
setInterval(() => {
  if (!state.topup || polling || state.busy || Date.now() > state.until) return;
  polling = true;
  call("wallet_view", {}).finally(() => {
    polling = false;
  });
}, POLL_MS);

// The result can be old (a reloaded conversation shows each card again), so the wallet is read again at once.
McpApp.on("ui/notifications/tool-result", (result) => {
  apply(result);
  if (state.cardId) call("wallet_view", {});
});
McpApp.on("ui/notifications/tool-input", () => undefined);
McpApp.on("ui/notifications/tool-cancelled", () => showNotice("The request was cancelled."));
McpApp.on("ui/resource-teardown", () => ({}));
const hostContext = (context) => {
  if (context?.theme) for (const theme of ["dark", "light"]) document.documentElement.classList.toggle(theme, context.theme === theme);
};
McpApp.on("ui/notifications/host-context-changed", hostContext);
hostContext({ theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light" });

McpApp.connect({ name: "wallet", title: "Wallet", version: "0.1.0" }).then(
  (hello) => hostContext(hello.hostContext),
  (error) => {
    root.textContent = `Could not connect to the chat: ${error.message}`;
  },
);
