// SPDX-License-Identifier: AGPL-3.0-or-later
// The menu card: a searchable menu with a cart. The person adds items, chooses where to deliver, and
// presses Review order; the card sends item ids, quantities and the area to the server, which prices the
// order and makes the quote. Prices on screen are for display only.
import { Cart } from "./cart.js";
import { categoriesOf, filterItems, indexOf } from "./catalog.js";
import { displayModes } from "./display.js";
import { fromTemplate, setText, show, slot } from "./dom.js";
import { MenuList } from "./list.js";
import { naira } from "./money.js";

const root = document.getElementById("root");
const state = { menu: null, index: [], prices: new Map(), query: "", category: "", cart: new Cart(), area: "", busy: false, notice: null, ordered: false };
let ui = null;

const plainError = (text) => (text ?? "").replace(/^[A-Z][A-Z_]+:\s*/, "");
const textOf = (result) => result.content?.find((block) => block.type === "text")?.text;
const capitalised = (word) => word[0].toUpperCase() + word.slice(1);

const modes = displayModes(
  document.documentElement,
  (mode) => McpApp.requestDisplayMode(mode),
  () => ui && refreshExpand(),
);

function refreshExpand() {
  const fullscreen = modes.state.mode === "fullscreen";
  show(ui.expand, fullscreen || modes.state.available.includes("fullscreen"));
  ui.expand.setAttribute("aria-label", fullscreen ? "Exit full screen" : "Full screen");
  show(slot(ui.expand, "expand-glyph"), !fullscreen);
  show(slot(ui.expand, "collapse-glyph"), fullscreen);
}

function refreshFooter() {
  const { cart, menu } = state;
  const cost = cart.subtotal((id) => state.prices.get(id));
  setText(ui.card, "count", `${cart.count} ${cart.count === 1 ? "item" : "items"}`);
  setText(ui.card, "total", naira(cost > 0 ? cost + menu.delivery_fee_kobo : 0));
  setText(ui.card, "delivery", cost > 0 ? `incl. ${naira(menu.delivery_fee_kobo)} delivery` : "");
  show(ui.clear, !cart.empty);
  ui.clear.disabled = state.busy;
  ui.area.disabled = state.busy;
  ui.order.disabled = state.busy || cart.empty;
  ui.order.toggleAttribute("aria-busy", state.busy);
  setText(ui.card, "notice", state.notice);
}

function applyFilter() {
  const found = filterItems(state.index, state.query, state.category);
  ui.list.items = found;
  show(ui.empty, found.length === 0);
  show(slot(ui.card, "items"), found.length > 0);
}

function buildChips(card) {
  const chips = slot(card, "chips");
  const categories = categoriesOf(state.menu.items);
  for (const category of categories.length ? ["", ...categories] : []) {
    const chip = fromTemplate("t-chip");
    chip.textContent = category ? capitalised(category) : "All";
    chip.dataset.category = category;
    chip.setAttribute("aria-pressed", String(category === state.category));
    chips.append(chip);
  }
}

function buildUi(menu) {
  const card = fromTemplate("t-menu");
  const cart = state.cart;
  const list = new MenuList({
    list: slot(card, "items"),
    scroller: slot(card, "scroller"),
    more: fromTemplate("t-more"),
    cart,
    all: menu.items,
    changed: refreshFooter,
  });
  const area = slot(card, "area");
  for (const name of menu.areas) area.add(new Option(name, name));
  state.area = menu.areas[0] ?? "";
  buildChips(card);
  return {
    card,
    list,
    area,
    search: slot(card, "search"),
    chips: slot(card, "chips"),
    empty: slot(card, "empty"),
    order: slot(card, "order"),
    clear: slot(card, "clear"),
    expand: slot(card, "expand"),
  };
}

function showMenu(menu) {
  if (state.ordered || state.menu?.card_id === menu.card_id) return;
  Object.assign(state, {
    menu,
    index: indexOf(menu.items),
    prices: new Map(menu.items.map((item) => [item.item_id, item.price_kobo])),
    query: "",
    category: "",
    notice: null,
  });
  state.cart.clear();
  ui = buildUi(menu);
  root.replaceChildren(ui.card);
  applyFilter();
  refreshFooter();
  refreshExpand();
}

async function showReady() {
  state.ordered = true;
  state.menu = null;
  ui = null;
  await modes.leave();
  root.replaceChildren(fromTemplate("t-ready"));
}

function showRefusal(text) {
  state.notice = plainError(text) || "The request was refused.";
  if (ui) return refreshFooter();
  const notice = fromTemplate("t-notice");
  notice.textContent = state.notice;
  root.replaceChildren(notice);
}

// What a tool result means to this card: a menu to show, an order that now waits for approval, or a refusal.
function apply(result) {
  if (result.isError) return showRefusal(textOf(result));
  const data = result.structuredContent ?? {};
  if (data.spawned) return showReady();
  if (data.items) return showMenu(data);
  showRefusal("The server sent a reply this card cannot show.");
}

async function order() {
  const items = state.cart.lines.map(([item_id, quantity]) => ({ item_id, quantity }));
  state.busy = true;
  state.notice = null;
  refreshFooter();
  try {
    await apply(await McpApp.callTool("order_from_menu", { card_id: state.menu.card_id, items, delivery_area: state.area }));
  } catch {
    showRefusal("The connection to the server was lost. Try again.");
  } finally {
    state.busy = false;
    if (ui) refreshFooter();
  }
}

function pickCategory(category) {
  state.category = category;
  for (const chip of ui.chips.children) chip.setAttribute("aria-pressed", String(chip.dataset.category === category));
  applyFilter();
}

const actions = {
  add: (button) => ui.list.press("add", button.dataset.item),
  more: (button) => ui.list.press("more", button.dataset.item),
  less: (button) => ui.list.press("less", button.dataset.item),
  chip: (button) => pickCategory(button.dataset.category),
  order,
  expand: () => modes.toggle(),
  clear() {
    state.cart.clear();
    ui.list.refresh();
    refreshFooter();
    ui.search.focus();
  },
};

root.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (button && ui) actions[button.dataset.action]?.(button);
});
root.addEventListener("input", (event) => {
  if (ui && event.target === ui.search) {
    state.query = ui.search.value;
    applyFilter();
  }
});
root.addEventListener("change", (event) => {
  if (ui && event.target === ui.area) state.area = ui.area.value;
});

McpApp.on("ui/notifications/tool-result", apply);
McpApp.on("ui/notifications/tool-input", () => undefined);
McpApp.on("ui/notifications/tool-cancelled", () => showRefusal("The request was cancelled."));
McpApp.on("ui/resource-teardown", () => ({}));
const hostContext = (context) => {
  if (context?.theme) for (const theme of ["dark", "light"]) document.documentElement.classList.toggle(theme, context.theme === theme);
  modes.adopt(context);
};
McpApp.on("ui/notifications/host-context-changed", hostContext);
hostContext({ theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light" });

McpApp.connect({ name: "menu", title: "Menu", version: "0.1.0" }, { availableDisplayModes: ["inline", "fullscreen"] }).then(
  (hello) => hostContext(hello.hostContext),
  (error) => {
    root.textContent = `Could not connect to the chat: ${error.message}`;
  },
);
