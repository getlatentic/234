// SPDX-License-Identifier: AGPL-3.0-or-later
// OKLCH to sRGB and the WCAG 2.x contrast ratio: the only colour maths the design tokens need.

const clamp01 = (v) => Math.min(1, Math.max(0, v));
const toLinear = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const fromLinear = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);

export function parseOklch(text) {
  const match = /^oklch\(\s*([\d.]+)%\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\s*\)$/.exec(text.trim());
  if (!match) throw new Error(`not an oklch() colour: ${text}`);
  const [, l, c, h, a] = match;
  return { l: Number(l) / 100, c: Number(c), h: Number(h), alpha: a === undefined ? 1 : Number(a) };
}

function linearRgb({ l, c, h }) {
  const a = c * Math.cos((h * Math.PI) / 180);
  const b = c * Math.sin((h * Math.PI) / 180);
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
    -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
    -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_,
  ];
}

const inGamut = (rgb) => rgb.every((v) => v >= -0.0005 && v <= 1.0005);

/** The sRGB colour of an oklch() string; a colour outside the gamut keeps its lightness and hue and loses chroma. */
export function toRgb(text) {
  const colour = parseOklch(text);
  let { c } = colour;
  let rgb = linearRgb({ ...colour, c });
  while (!inGamut(rgb) && c > 0) {
    c = Math.max(0, c - 0.002);
    rgb = linearRgb({ ...colour, c });
  }
  return { rgb: rgb.map((v) => Math.round(clamp01(fromLinear(clamp01(v))) * 255)), alpha: colour.alpha };
}

const hex2 = (n) => n.toString(16).padStart(2, "0");

/** #rrggbb, or #rrggbbaa when the colour is translucent. */
export function toHex(text) {
  const { rgb, alpha } = toRgb(text);
  return `#${rgb.map(hex2).join("")}${alpha < 1 ? hex2(Math.round(alpha * 255)) : ""}`;
}

export const rgbOfHex = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

export function luminance([r, g, b]) {
  return 0.2126 * toLinear(r / 255) + 0.7152 * toLinear(g / 255) + 0.0722 * toLinear(b / 255);
}

export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** `top` (an rgb triple with alpha) laid over an opaque `under`. */
export const over = ({ rgb, alpha }, under) => rgb.map((v, i) => Math.round(v * alpha + under[i] * (1 - alpha)));
