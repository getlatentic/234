// SPDX-License-Identifier: AGPL-3.0-or-later
// The contrast the palette has to reach, as data: every text or control colour against every surface it
// is drawn on, in both themes. WCAG 2.x AA: 4.5 for text, 3 for the parts of a control and the focus ring.
import { contrast, rgbOfHex, toHex } from "./color.mjs";

const SURFACES = ["ground", "raised", "sunken", "mint"];
const TEXT = ["ink", "ink-2", "ink-3"];
const STATUS = ["ok", "warn", "bad"];
const TILES = ["main", "soup", "side", "drink"];
const PRIMARY_STEPS = ["primary", "primary-hover", "primary-pressed"];

/** [foreground token, background token, minimum ratio, what it is]. */
export const PAIRS = [
  ...TEXT.flatMap((fg) => SURFACES.map((bg) => [fg, bg, 4.5, "text"])),
  ...PRIMARY_STEPS.map((bg) => ["on-primary", bg, 4.5, "the label of the primary action"]),
  ...SURFACES.map((bg) => ["primary", bg, 4.5, "the primary as a ring, an edge or text"]),
  ...SURFACES.map((bg) => ["mark", bg, 4.5, "the numerals of the wordmark"]),
  ...["ground", "raised", "mint"].map((bg) => ["line-strong", bg, 3, "the edge of a field or a control"]),
  ["google-ink", "google-surface", 4.5, "the label of Google's sign-in button"],
  ["google-edge", "google-surface", 3, "the edge of Google's sign-in button"],
  ["google-edge", "raised", 3, "Google's button edge on the drawer"],
  ["google-surface", "raised", 1, "Google's button against the drawer (a neutral surface, not a tint)"],
  ...STATUS.flatMap((s) => [
    ...[...SURFACES, `${s}-soft`].map((bg) => [s, bg, 4.5, `${s} text and icon`]),
    ["ink", `${s}-soft`, 4.5, `text on the ${s} tint`],
    ["ink-2", `${s}-soft`, 4.5, `secondary text on the ${s} tint`],
  ]),
  ...TILES.map((t) => [`tile-${t}-ink`, `tile-${t}`, 4.5, "a drawn tile"]),
  ...TILES.map((t) => [`tile-${t}-ink`, "raised", 3, "a drawn tile on a card"]),
];

const rgbOf = (colors, name) => rgbOfHex(toHex(colors[name]));

/** Every pair for one theme with the ratio it reaches; `failing` are the ones under their minimum. */
export function measure(colors) {
  const rows = PAIRS.map(([fg, bg, minimum, what]) => {
    const ratio = contrast(rgbOf(colors, fg), rgbOf(colors, bg));
    return { fg, bg, minimum, what, ratio, ok: ratio >= minimum };
  });
  return { rows, failing: rows.filter((r) => !r.ok) };
}

/** The brand greens and mint are for graphics (the plus, the symbol, illustrations, tints). Each must stay under
 *  the 4.5:1 of text on white, so that nothing can quietly be set in them: `measureGraphics` gives the numbers. */
export const GRAPHIC_ONLY = ["brand.green", "brand.bright", "brand.vivid", "brand.mint", "brand.mint-soft"];

export function measureGraphics(brand) {
  const hex = (name) => toHex(brand[name.slice("brand.".length)]);
  const grounds = { white: "#ffffff", "warm ground": toHex("oklch(97.8% .008 90)") };
  return GRAPHIC_ONLY.map((name) => ({
    name,
    hex: hex(name),
    ratios: Object.fromEntries(Object.entries(grounds).map(([ground, value]) => [ground, contrast(rgbOfHex(hex(name)), rgbOfHex(value))])),
  }));
}
