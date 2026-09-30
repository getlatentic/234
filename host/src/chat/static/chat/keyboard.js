// SPDX-License-Identifier: AGPL-3.0-or-later
// The space a virtual keyboard takes from the bottom of the layout viewport, published as --keyboard-inset so
// the composer can sit above it. Browsers that resize the layout viewport for the keyboard report 0 here.

export function keyboardInset(viewport, layoutHeight) {
  if (viewport.scale !== 1) return 0;
  return Math.max(0, Math.round(layoutHeight - viewport.height - viewport.offsetTop));
}

export function trackKeyboard(root = document.documentElement) {
  const viewport = window.visualViewport;
  if (!viewport) return;
  const publish = () => root.style.setProperty("--keyboard-inset", `${keyboardInset(viewport, innerHeight)}px`);
  viewport.addEventListener("resize", publish);
  viewport.addEventListener("scroll", publish);
  publish();
}
