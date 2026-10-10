// SPDX-License-Identifier: AGPL-3.0-or-later
// The wallet card: the balance and the latest entries as the server holds them; Add money, which asks the
// server for a checkout and opens it; and Withdraw: the amount, the bank and the account number, then the name
// the bank gives for the account, which the person confirms by pressing Withdraw. Money arrives only through the
// checkout's webhook and leaves only on that press; the card reads the wallet again until either shows.
const POLL_MS = 3000;
const POLL_FOR_MS = 30 * 60 * 1000;
const MIN_NAIRA = 100;
const root = document.getElementById("root");
const state = {
  cardId: null,
  wallet: null,
  topup: null,
  withdrawal: null,
  token: null,
  view: "wallet",
  busy: false,
  notice: "",
  fields: { amount: "", "out-amount": "", "out-bank": "", "out-account": "" },
  until: 0,
};

const fromTemplate = (id) => document.getElementById(id).content.firstElementChild.cloneNode(true);
const slot = (node, name) => node.querySelector(`[data-slot="${name}"]`);
const show = (node, on) => node.toggleAttribute("hidden", !on);
const plainError = (text) => (text ?? "").replace(/^[A-Z][A-Z_]+:\s*/, "");
const textOf = (result) => result.content?.find((block) => block.type === "text")?.text;
const naira = (text) => Number((text ?? "").replace(/[\s,₦]/g, ""));
const sending = () => state.withdrawal?.state === "sent";

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

function walletView() {
  const card = fromTemplate("t-wallet");
  const { wallet } = state;
  setText(card, "balance", wallet.balance);
  slot(card, "entries").replaceChildren(...wallet.entries.map(entryOf));
  setText(card, "pay", state.topup ? `Pay ${state.topup.amount}` : "");
  show(slot(card, "withdraw"), wallet.balanceKobo > 0 && !wallet.frozen);
  setText(card, "status", sending() ? `${state.withdrawal.status} ${state.withdrawal.amount}` : "");
  return card;
}

function confirmView() {
  const card = fromTemplate("t-confirm");
  const { withdrawal } = state;
  slot(card, "amount").textContent = withdrawal.amount;
  slot(card, "name").textContent = withdrawal.accountName;
  slot(card, "account").textContent = `${withdrawal.bank} ${withdrawal.accountMasked}`;
  return card;
}

const views = { wallet: walletView, withdraw: () => fromTemplate("t-withdraw"), confirm: confirmView };

function draw() {
  const focused = document.activeElement?.dataset?.slot;
  const card = views[state.view]();
  for (const [name, value] of Object.entries(state.fields)) {
    const field = slot(card, name);
    if (field) field.value = value;
  }
  setText(card, "notice", state.notice);
  root.replaceChildren(card);
  if (focused && slot(card, focused)) slot(card, focused).focus();
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

function keepWithdrawal(result, data) {
  if (!data.withdrawal) return;
  state.withdrawal = data.withdrawal;
  const token = result._meta?.withdrawalToken;
  if (token) {
    state.token = token;
    state.view = "confirm";
  } else if (data.withdrawal.state !== "open") {
    state.view = "wallet";
    state.until = Date.now() + POLL_FOR_MS;
  }
}

// A result names its card and carries the wallet as it stands; a top-up carries its checkout, and a withdrawal
// its account and how it stands.
function apply(result) {
  if (result.isError) return showNotice(textOf(result));
  const data = result.structuredContent;
  if (!data?.wallet || !data.card_id) return showNotice("The server sent a reply this card cannot show.");
  const arrived = state.topup && data.wallet.balanceKobo > state.wallet.balanceKobo;
  state.cardId = data.card_id;
  state.wallet = data.wallet;
  if (data.topup) state.topup = data.topup;
  if (arrived) state.topup = null;
  keepWithdrawal(result, data);
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
  const amount = naira(state.fields.amount);
  if (!Number.isInteger(amount) || amount < MIN_NAIRA) return showNotice(`Enter at least ₦${MIN_NAIRA}.`);
  await act(() => call("start_topup", { amount_naira: amount }));
  if (!state.topup?.checkoutUrl || state.notice) return;
  state.fields.amount = "";
  state.until = Date.now() + POLL_FOR_MS;
  draw();
  await openPayment();
}

function goTo(view) {
  state.view = view;
  state.notice = "";
  draw();
}

async function checkAccount() {
  const amount = naira(state.fields["out-amount"]);
  if (!Number.isInteger(amount) || amount < MIN_NAIRA) return showNotice(`Enter at least ₦${MIN_NAIRA}.`);
  const account = state.fields["out-account"].replace(/[\s-]/g, "");
  if (!/^\d{10}$/.test(account)) return showNotice("Enter the 10 digit account number.");
  if (!state.fields["out-bank"].trim()) return showNotice("Enter the bank.");
  await act(() => call("start_withdrawal", { amount_naira: amount, bank: state.fields["out-bank"].trim(), account_number: account }));
}

async function confirmWithdrawal() {
  const { withdrawal, token } = state;
  const args = { withdrawal_id: withdrawal.id, withdrawal_token: token, displayed_amount_kobo: withdrawal.amountKobo, confirmed_name: withdrawal.accountName };
  await act(() => call("withdraw", args));
  if (state.view !== "wallet") return;
  state.token = null;
  for (const name of ["out-amount", "out-bank", "out-account"]) state.fields[name] = "";
  draw();
}

const actions = {
  add: addMoney,
  pay: () => state.topup && openPayment(),
  withdraw: () => goTo("withdraw"),
  check: checkAccount,
  confirm: confirmWithdrawal,
  back: () => goTo("wallet"),
};

root.addEventListener("click", (event) => {
  const name = event.target.closest("button[data-action]")?.dataset.action;
  if (name && state.wallet && !state.busy) actions[name]?.();
});
root.addEventListener("input", (event) => {
  const name = event.target.dataset.slot;
  if (name in state.fields) state.fields[name] = event.target.value;
});
// A sandboxed view may not submit forms, so each form goes by its button or by Enter in its fields.
root.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || state.busy || !(event.target.dataset.slot in state.fields)) return;
  (state.view === "withdraw" ? checkAccount : addMoney)();
});

let polling = false;
setInterval(() => {
  const waiting = state.topup || sending();
  if (!waiting || polling || state.busy || Date.now() > state.until) return;
  polling = true;
  const args = sending() ? { withdrawal_id: state.withdrawal.id } : {};
  call("wallet_view", args).finally(() => {
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
