// SPDX-License-Identifier: AGPL-3.0-or-later
// The chat host's theme, in the names ext-apps gives a view (`hostContext.styles.variables`, specification
// 2026-01-26, "Theming"): each colour is light-dark(light, dark) so a view that sets its own colour-scheme gets
// the right one, and the rest are the host's own type, radii and shadows. Only what the host has is passed;
// a view keeps its own default for the names left out (no info colours: the palette has no such role).
import { toHex } from "./color.mjs";

const SANS = "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, \"Noto Sans\", sans-serif";
const MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

const COLORS = {
  "--color-background-primary": "ground",
  "--color-background-secondary": "raised",
  "--color-background-tertiary": "sunken",
  "--color-background-inverse": "ink",
  "--color-background-danger": "bad-soft",
  "--color-background-success": "ok-soft",
  "--color-background-warning": "warn-soft",
  "--color-background-disabled": "sunken",
  "--color-text-primary": "ink",
  "--color-text-secondary": "ink-2",
  "--color-text-tertiary": "ink-3",
  "--color-text-inverse": "ground",
  "--color-text-danger": "bad",
  "--color-text-success": "ok",
  "--color-text-warning": "warn",
  "--color-text-disabled": "ink-3",
  "--color-border-primary": "line-strong",
  "--color-border-secondary": "line",
  "--color-border-tertiary": "line",
  "--color-border-inverse": "ink",
  "--color-border-danger": "bad",
  "--color-border-success": "ok",
  "--color-border-warning": "warn",
  "--color-border-disabled": "line",
  "--color-ring-primary": "primary",
  "--color-ring-secondary": "line-strong",
  "--color-ring-inverse": "on-primary",
  "--color-ring-danger": "bad",
  "--color-ring-success": "ok",
  "--color-ring-warning": "warn",
};

const TYPE = {
  "--font-sans": SANS,
  "--font-mono": MONO,
  "--font-weight-normal": "400",
  "--font-weight-medium": "500",
  "--font-weight-semibold": "600",
  "--font-weight-bold": "700",
  "--font-text-xs-size": "0.75rem",
  "--font-text-sm-size": "0.875rem",
  "--font-text-md-size": "1rem",
  "--font-text-lg-size": "1.125rem",
  "--font-text-xs-line-height": "1rem",
  "--font-text-sm-line-height": "1.25rem",
  "--font-text-md-line-height": "1.5rem",
  "--font-text-lg-line-height": "1.75rem",
};

export function hostStyleVariables(tokens) {
  const colours = Object.fromEntries(
    Object.entries(COLORS).map(([name, token]) => [name, `light-dark(${toHex(tokens.colors.light[token])}, ${toHex(tokens.colors.dark[token])})`]),
  );
  const radii = {
    "--border-radius-xs": "0.25rem",
    "--border-radius-sm": "0.5rem",
    "--border-radius-md": tokens.shape["r-control"],
    "--border-radius-lg": tokens.shape["r-card"],
    "--border-radius-xl": tokens.shape["r-sheet"],
    "--border-radius-full": "9999px",
    "--border-width-regular": "1px",
  };
  const edge = `light-dark(${toHex(tokens.colors.light.line)}, ${toHex(tokens.colors.dark.line)})`;
  const shade = `light-dark(${toHex(tokens.colors.light.shadow)}, ${toHex(tokens.colors.dark.shadow)})`;
  const shadows = {
    "--shadow-hairline": `0 0 0 1px ${edge}`,
    "--shadow-sm": `0 1px 2px ${shade}`,
    "--shadow-md": `0 4px 12px -2px ${shade}`,
    "--shadow-lg": `0 8px 24px -8px ${shade}`,
  };
  return { ...colours, ...TYPE, ...radii, ...shadows };
}
