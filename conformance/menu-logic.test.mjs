// SPDX-License-Identifier: AGPL-3.0-or-later
// The menu card's pure logic, without a browser: search and categories, and the cart's limits.
// usage: node --test conformance/menu-logic.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { Cart, MAX_LINES, MAX_PER_ITEM } from "../card/menu/src/cart.js";
import { categoriesOf, filterItems, indexOf } from "../card/menu/src/catalog.js";

const menu = [
  { item_id: "jollof", name: "Jollof rice with fried chicken", note: "Party jollof, fried plantain", category: "mains" },
  { item_id: "moi", name: "Moi moi, 2 wraps", note: "Steamed bean pudding with egg", category: "sides" },
  { item_id: "egusi", name: "Ẹ̀gúsí soup with pounded yam", note: "Assorted meat", category: "soups" },
  { item_id: "zobo", name: "Zobo, 500ml", note: "Chilled hibiscus drink", category: "drinks" },
];
const index = indexOf(menu);
const ids = (query, category = "") => filterItems(index, query, category).map((item) => item.item_id);

test("search ignores case, accents, punctuation and spacing", () => {
  assert.deepEqual(ids("MOI MOI"), ["moi"]);
  assert.deepEqual(ids("moimoi"), ["moi"]);
  assert.deepEqual(ids("Moi-moi"), ["moi"]);
  assert.deepEqual(ids("egusi"), ["egusi"]);
  assert.deepEqual(ids("ẹ̀gúsí"), ["egusi"]);
});

test("every word must match, in any order, in the name, the note or the category", () => {
  assert.deepEqual(ids("chicken jollof"), ["jollof"]);
  assert.deepEqual(ids("steamed egg"), ["moi"]);
  assert.deepEqual(ids("drinks"), ["zobo"]);
  assert.deepEqual(ids("jollof zobo"), []);
});

test("an empty query keeps the menu's order, and a category narrows it", () => {
  assert.deepEqual(ids(""), ["jollof", "moi", "egusi", "zobo"]);
  assert.deepEqual(ids("", "soups"), ["egusi"]);
  assert.deepEqual(ids("rice", "sides"), []);
});

test("a query of punctuation alone matches everything, as an empty one does", () => {
  assert.deepEqual(ids(" , "), ids(""));
});

test("categories appear in menu order, and only when there is more than one", () => {
  assert.deepEqual(categoriesOf(menu), ["mains", "sides", "soups", "drinks"]);
  assert.deepEqual(categoriesOf(menu.slice(0, 1)), []);
  assert.deepEqual(categoriesOf(menu.map((item) => ({ ...item, category: "mains" }))), []);
  assert.deepEqual(categoriesOf(menu.map(({ category, ...item }) => item)), []);
});

test("the cart stops at ten of one item and never goes below zero", () => {
  const cart = new Cart();
  for (let n = 0; n < 15; n += 1) cart.step("a", 1);
  assert.equal(cart.quantity("a"), MAX_PER_ITEM);
  assert.equal(cart.canAdd("a"), false);
  for (let n = 0; n < 15; n += 1) cart.step("a", -1);
  assert.equal(cart.quantity("a"), 0);
  assert.equal(cart.empty, true);
});

test("the cart holds at most twelve different items", () => {
  const cart = new Cart();
  for (let n = 0; n < MAX_LINES; n += 1) cart.step(`item-${n}`, 1);
  assert.equal(cart.canAdd("item-99"), false);
  assert.equal(cart.canAdd("item-0"), true);
  cart.step("item-0", -1);
  assert.equal(cart.canAdd("item-99"), true);
});

test("the subtotal and the count come from the quantities and the given prices", () => {
  const cart = new Cart();
  cart.step("a", 2);
  cart.step("b", 1);
  assert.equal(cart.count, 3);
  assert.equal(cart.subtotal((id) => ({ a: 100, b: 250 })[id]), 450);
  cart.clear();
  assert.equal(cart.subtotal(() => 1), 0);
});
