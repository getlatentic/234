// SPDX-License-Identifier: AGPL-3.0-or-later
export const MAX_PER_ITEM = 10;
export const MAX_LINES = 12;

/** What the person has picked: a quantity for each item id. The server prices it; nothing here does. */
export class Cart {
  #quantities = new Map();

  quantity(id) {
    return this.#quantities.get(id) ?? 0;
  }

  get lines() {
    return [...this.#quantities].filter(([, quantity]) => quantity > 0);
  }

  get count() {
    return this.lines.reduce((sum, [, quantity]) => sum + quantity, 0);
  }

  get empty() {
    return this.lines.length === 0;
  }

  canAdd(id) {
    const quantity = this.quantity(id);
    return quantity < MAX_PER_ITEM && (quantity > 0 || this.lines.length < MAX_LINES);
  }

  step(id, change) {
    const next = Math.min(Math.max(this.quantity(id) + change, 0), MAX_PER_ITEM);
    if (next === 0) this.#quantities.delete(id);
    else this.#quantities.set(id, next);
  }

  clear() {
    this.#quantities.clear();
  }

  subtotal(priceOf) {
    return this.lines.reduce((sum, [id, quantity]) => sum + priceOf(id) * quantity, 0);
  }
}
