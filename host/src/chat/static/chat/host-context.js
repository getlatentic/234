// SPDX-License-Identifier: AGPL-3.0-or-later
// What the host tells a card about where it is shown (`hostContext`, ext-apps specification 2026-01-26,
// "Host Context in McpUiInitializeResult"), and the tell-tales that change it while the card is open.
import { HOST_STYLE_VARIABLES } from "./host-styles.js";

export const DISPLAY_MODES = ["inline", "fullscreen"];
export const MAX_HEIGHT = 6000;

const dark = matchMedia("(prefers-color-scheme: dark)");

const theme = () => (dark.matches ? "dark" : "light");

/** The safe-area insets in pixels, read from a probe because CSS `env()` has no JavaScript form. */
function safeAreaInsets() {
  const probe = document.createElement("div");
  probe.style.cssText =
    "position:fixed;visibility:hidden;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)";
  document.body.append(probe);
  const style = getComputedStyle(probe);
  const insets = ["Top", "Right", "Bottom", "Left"].map((side) => Math.round(parseFloat(style[`padding${side}`]) || 0));
  probe.remove();
  return { top: insets[0], right: insets[1], bottom: insets[2], left: insets[3] };
}

export function containerDimensions(frame, mode) {
  const width = Math.round(frame.getBoundingClientRect().width);
  return mode === "fullscreen" ? { height: Math.round(frame.getBoundingClientRect().height), width } : { maxHeight: MAX_HEIGHT, width };
}

/** The whole context: `setHostContext` replaces what the bridge holds, so a change is made on a copy of this. */
export function hostContext(frame, mode = "inline") {
  return {
    theme: theme(),
    styles: { variables: HOST_STYLE_VARIABLES },
    displayMode: mode,
    availableDisplayModes: DISPLAY_MODES,
    containerDimensions: containerDimensions(frame, mode),
    locale: navigator.language,
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    userAgent: document.querySelector('meta[name="application-name"]')?.content ?? "chat host",
    platform: "web",
    deviceCapabilities: { touch: navigator.maxTouchPoints > 0, hover: matchMedia("(hover: hover)").matches },
    safeAreaInsets: safeAreaInsets(),
  };
}

/** Calls `changed` when the theme, the frame's size or the safe area changes; returns the way to stop. */
export function watchContext(frame, changed) {
  const resize = new ResizeObserver(changed);
  resize.observe(frame);
  dark.addEventListener("change", changed);
  addEventListener("orientationchange", changed);
  return () => {
    resize.disconnect();
    dark.removeEventListener("change", changed);
    removeEventListener("orientationchange", changed);
  };
}
