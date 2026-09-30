// SPDX-License-Identifier: AGPL-3.0-or-later
// Shared by the card runs that mount a card in the official-AppBridge host page (card-states-host.html):
// the host page itself (its background is the design tokens' ground, so a card sits on what the chat page
// paints), waiting until the card has stopped resizing, and the WCAG contrast of what it paints.
import { readFile } from "node:fs/promises";
import { toHex } from "../design/color.mjs";
import { loadTokens } from "../design/tokens.mjs";

const tokens = async () => loadTokens();

export async function hostPageHtml() {
  const { colors } = await tokens();
  const page = await readFile(new URL("card-states-host.html", import.meta.url), "utf8");
  return page.replace("%GROUND_LIGHT%", toHex(colors.light.ground)).replace("%GROUND_DARK%", toHex(colors.dark.ground));
}

/** Resolves with the card's height once it has reported the same size four times (or after six seconds). */
export const settle = (page) =>
  page.evaluate(
    () =>
      new Promise((resolve) => {
        let last = -1;
        let stable = 0;
        const timer = setInterval(() => {
          stable = window.__height === last && window.__height > 0 ? stable + 1 : 0;
          last = window.__height;
          if (stable >= 4) { clearInterval(timer); resolve(last); }
        }, 100);
        setTimeout(() => { clearInterval(timer); resolve(last); }, 6000);
      }),
  );


// The contrast of every visible text node against what is painted behind it (WCAG 2.x, AA).
export const contrastReport = () => {
  const paint = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  const rgba = (css) => {
    paint.clearRect(0, 0, 1, 1);
    paint.fillStyle = "#000";
    paint.fillStyle = css;
    paint.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = paint.getImageData(0, 0, 1, 1).data;
    return [r, g, b, a / 255];
  };
  const over = (top, under) => {
    const a = top[3] + under[3] * (1 - top[3]);
    return [0, 1, 2].map((i) => (top[i] * top[3] + under[i] * under[3] * (1 - top[3])) / (a || 1)).concat(a);
  };
  const lum = ([r, g, b]) => {
    const f = (v) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const page = rgba(getComputedStyle(document.documentElement).getPropertyValue("--ground").trim() || "#fff");
  const backdrop = (el) => {
    let color = [0, 0, 0, 0];
    for (let n = el; n; n = n.parentElement) color = over(color, rgba(getComputedStyle(n).backgroundColor));
    return over(color, page);
  };
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const el = node.parentElement;
    if (!node.textContent.trim() || !el.getClientRects().length || el.closest("template")) continue;
    const style = getComputedStyle(el);
    if (style.visibility === "hidden" || Number(style.opacity) === 0) continue;
    const bg = backdrop(el);
    const fg = over(rgba(style.color), bg);
    const [hi, lo] = [lum(fg), lum(bg)].sort((x, y) => y - x);
    const ratio = (hi + 0.05) / (lo + 0.05);
    const px = parseFloat(style.fontSize);
    const large = px >= 24 || (px >= 18.66 && Number(style.fontWeight) >= 700);
    const disabled = el.closest("button:disabled, input:disabled");
    if (ratio < (large ? 3 : 4.5) && !disabled) out.push({ text: node.textContent.trim().slice(0, 40), ratio: Math.round(ratio * 100) / 100 });
  }
  return out;
};

