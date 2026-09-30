// SPDX-License-Identifier: AGPL-3.0-or-later
// The geometry of the mark, in one place. Lengths are in the units of the traced numerals
// (design/mark/numerals.svg: 903 wide, 376 tall, y down), measured on the concept brand boards (docs/brand.md).
//
// The plus is built of pills ("leaves"): a rectangle whose two outer corners are fully round, whose inner
// corner on one side is round with the rest of its length, and whose other inner corner is square. In the
// logo three of them stand on the 4's upper right; the 4 itself stands in for the fourth. The symbol is the
// same idea with four, turned a half circle about the centre.
import { readFileSync } from "node:fs";

const read = (name) => readFileSync(new URL(`./mark/${name}.svg`, import.meta.url), "utf8");

function traced(name) {
  const text = read(name);
  const [, w, h] = /viewBox="0 0 ([\d.]+) ([\d.]+)"/.exec(text);
  return { d: /<path[^>]* d="([^"]+)"/.exec(text)[1], width: Number(w), height: Number(h) };
}

export const NUMERALS = traced("numerals");
export const ASK = traced("ask");

/** The plus in the logo's frame (x right, y down; the numerals occupy 0..903 by 0..376). */
export const PLUS = {
  top: "M858 29V-16A45 45 0 0 0 768 -16A45 45 0 0 0 813 29Z",
  right: "M858 24H903A48 48 0 0 1 903 120H858Z",
  mint: "M768 24H858V126A45 45 0 0 1 768 126Z",
};

/** The logo's box: the numerals, and the plus above and to the right of the 4. */
export const LOGO_BOX = { x: 0, y: -61, width: 951, height: 437 };

/** The four-pill symbol in a 100 x 100 box: top, left, right, bottom. */
export const SYMBOL = {
  top: "M70 32V20A20 20 0 0 0 30 20A12 12 0 0 0 42 32Z",
  left: "M50 32H18A18 18 0 0 0 18 68H50Z",
  right: "M50 32H82A18 18 0 0 1 82 68H50Z",
  bottom: "M30 68V80A20 20 0 0 0 70 80A12 12 0 0 0 58 68Z",
};

const ROUND = 0.972; // the lockup's second line is set to the logo's width (see lockup())

/**
 * "Ask 234." under the logo, in the logo's frame. The second line is 'Ask', the numerals scaled to the cap
 * height of the A, and a round stop, all at one scale so the line is as wide as the logo with its plus.
 */
export function lockup() {
  const scale = ROUND;
  const cap = 170 * scale;
  const digits = cap / (NUMERALS.height - 24);
  const dot = 55 * scale;
  const top = LOGO_BOX.y + LOGO_BOX.height + 52;
  const baseline = top + cap;
  const askWidth = ASK.width * scale;
  const digitsX = askWidth + 32 * scale;
  const dotX = digitsX + NUMERALS.width * digits + 6 * scale;
  return {
    ask: `translate(0 ${top - 0}) scale(${scale})`,
    digits: `translate(${digitsX.toFixed(1)} ${(baseline - NUMERALS.height * digits).toFixed(1)}) scale(${digits.toFixed(4)})`,
    dot: { cx: dotX + dot / 2, cy: baseline + 3 - dot / 2, r: dot / 2 },
    box: { x: 0, y: LOGO_BOX.y, width: LOGO_BOX.width, height: baseline + 8 - LOGO_BOX.y },
    width: dotX + dot,
  };
}
