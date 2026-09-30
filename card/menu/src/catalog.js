// SPDX-License-Identifier: AGPL-3.0-or-later
// Finding items in a menu as a person types: names, notes and categories, ignoring case, accents and
// punctuation ("moi moi", "Moi-moi" and "moimoi" all find "Moi moi, 2 wraps").

const normalize = (text) =>
  String(text ?? "")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();

/** Each item with the text it is searched in, computed once. */
export function indexOf(items) {
  return items.map((item) => {
    const words = normalize(`${item.name} ${item.note ?? ""} ${item.category ?? ""}`);
    return { item, words, compact: words.replaceAll(" ", "") };
  });
}

function matcher(query) {
  const tokens = normalize(query).split(" ").filter(Boolean);
  const glued = tokens.join("");
  return (entry) => tokens.every((token) => entry.words.includes(token)) || (glued !== "" && entry.compact.includes(glued));
}

/** The items matching the query, in the menu's order, within one category (or all of them when it is empty). */
export function filterItems(index, query, category) {
  const matches = matcher(query);
  return index.filter((entry) => (!category || entry.item.category === category) && matches(entry)).map((entry) => entry.item);
}

/** The distinct categories in the order they first appear; none when the menu has fewer than two. */
export function categoriesOf(items) {
  const seen = [...new Set(items.map((item) => item.category).filter(Boolean))];
  return seen.length > 1 ? seen : [];
}
