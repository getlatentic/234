// SPDX-License-Identifier: AGPL-3.0-or-later
// What stands in for a photo: a drawing for the item (its `art`), tinted by its category. A real merchant's
// `image_url` replaces it, and the drawing is what shows when the picture cannot load.
import { slot } from "./dom.js";

const TONES = {
  mains: "bg-tile-main text-tile-main-ink",
  soups: "bg-tile-soup text-tile-soup-ink",
  sides: "bg-tile-side text-tile-side-ink",
  drinks: "bg-tile-drink text-tile-drink-ink",
};
const NEUTRAL = "bg-sunken text-ink-2";
const DRAWINGS = ["plate", "soup", "skewer", "wrap", "dough", "cup", "bottle"];
const SVG = "http://www.w3.org/2000/svg";

function drawing(item) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 48 48");
  svg.setAttribute("class", "size-10");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG, "use");
  use.setAttribute("href", `#art-${DRAWINGS.includes(item.art) ? item.art : "plate"}`);
  svg.append(use);
  return svg;
}

function picture(item) {
  const image = new Image();
  image.alt = "";
  image.loading = "lazy";
  image.decoding = "async";
  image.referrerPolicy = "no-referrer";
  image.className = "size-full object-cover";
  image.src = item.image_url;
  return image;
}

/** The tile of a row. The picture is used only when the item has an https one; if it does not load (the
 * view declares no origin for it, or the merchant's server is down) the drawing takes its place. */
export function fillTile(row, item) {
  const tile = slot(row, "tile");
  tile.className = `grid size-14 shrink-0 place-items-center overflow-hidden rounded-control ${TONES[item.category] ?? NEUTRAL}`;
  if (!/^https:\/\//i.test(item.image_url ?? "")) return tile.replaceChildren(drawing(item));
  const image = picture(item);
  image.addEventListener("error", () => tile.replaceChildren(drawing(item)), { once: true });
  tile.replaceChildren(image);
}
