// SPDX-License-Identifier: AGPL-3.0-or-later
// The rows of a menu. A real merchant's menu can have hundreds of items, so rows are built when first
// wanted and shown a chunk at a time: the next chunk comes when the end of the list scrolls into view,
// or when the person presses "Show more".
import { fillTile } from "./art.js";
import { fromTemplate, setText, show, slot } from "./dom.js";
import { naira } from "./money.js";

const CHUNK = 30;

export class MenuList {
  #rows = new Map();
  #visible = [];
  #shown = 0;
  #observer = null;

  constructor({ list, scroller, more, cart, all, changed }) {
    Object.assign(this, { list, scroller, more, cart, all, changed });
    more.querySelector("button").addEventListener("click", () => this.#extend());
    if ("IntersectionObserver" in window) {
      this.#observer = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && this.#extend(), {
        root: scroller,
        rootMargin: "200px",
      });
      this.#observer.observe(more);
    }
  }

  get renderedRows() {
    return this.list.querySelectorAll("li[data-item]").length;
  }

  /** Shows these items (already filtered, in menu order) from the top. */
  set items(items) {
    this.#visible = items;
    this.#shown = 0;
    this.list.replaceChildren();
    this.#extend();
    this.scroller.scrollTop = 0;
  }

  get shownCount() {
    return this.#visible.length;
  }

  #extend() {
    const next = this.#visible.slice(this.#shown, this.#shown + CHUNK);
    if (next.length) {
      this.list.append(...next.map((item) => this.#row(item)));
      this.#shown += next.length;
    }
    this.list.append(this.more);
    show(this.more, this.#shown < this.#visible.length);
  }

  #row(item) {
    let row = this.#rows.get(item.item_id);
    if (!row) {
      row = this.#build(item);
      this.#rows.set(item.item_id, row);
    }
    this.#refresh(row, item);
    return row;
  }

  #build(item) {
    const row = fromTemplate("t-row");
    row.dataset.item = item.item_id;
    setText(row, "name", item.name);
    setText(row, "note", item.note);
    setText(row, "price", naira(item.price_kobo));
    fillTile(row, item);
    if (!item.available) {
      slot(row, "name").classList.add("text-ink-3");
      show(slot(row, "add"), false);
      show(slot(row, "sold-out"), true);
      return row;
    }
    slot(row, "add").setAttribute("aria-label", `Add ${item.name}`);
    slot(row, "stepper").setAttribute("aria-label", item.name);
    slot(row, "less").setAttribute("aria-label", `One less ${item.name}`);
    slot(row, "more").setAttribute("aria-label", `One more ${item.name}`);
    for (const name of ["add", "less", "more"]) slot(row, name).dataset.item = item.item_id;
    return row;
  }

  #refresh(row, item) {
    if (!item.available) return;
    const quantity = this.cart.quantity(item.item_id);
    const allowed = this.cart.canAdd(item.item_id);
    show(slot(row, "add"), quantity === 0);
    show(slot(row, "stepper"), quantity > 0);
    slot(row, "add").disabled = !allowed;
    slot(row, "more").disabled = !allowed;
    slot(row, "quantity").textContent = quantity;
  }

  /** Brings every built row up to date with the cart (adding a 13th line disables the rest). */
  refresh() {
    for (const item of this.all) {
      const row = this.#rows.get(item.item_id);
      if (row) this.#refresh(row, item);
    }
  }

  /** One press of Add, plus or minus; focus follows the control that replaces the one pressed. */
  press(action, id) {
    this.cart.step(id, action === "less" ? -1 : 1);
    this.refresh();
    const row = this.#rows.get(id);
    const wanted = this.cart.quantity(id) === 0 ? "add" : action === "add" ? "more" : action;
    slot(row, slot(row, wanted).disabled ? "less" : wanted).focus();
    this.changed();
  }
}
