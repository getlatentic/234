// SPDX-License-Identifier: AGPL-3.0-or-later
// Display modes: the card offers full screen only when the host lists it, asks the host for it, and shows
// whichever mode the host says it is in. Escape leaves full screen.
export function displayModes(root, request, changed) {
  const state = { mode: "inline", available: [] };
  const adopt = (context) => {
    if (!context) return;
    if (Array.isArray(context.availableDisplayModes)) state.available = context.availableDisplayModes;
    if (context.displayMode) state.mode = context.displayMode;
    root.dataset.mode = state.mode;
    changed(state);
  };
  const ask = async (mode) => {
    try {
      adopt({ displayMode: (await request(mode))?.mode ?? state.mode });
    } catch {
      adopt({});
    }
  };
  addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.mode === "fullscreen") ask("inline");
  });
  return {
    state,
    adopt,
    toggle: () => ask(state.mode === "fullscreen" ? "inline" : "fullscreen"),
    leave: () => (state.mode === "fullscreen" ? ask("inline") : undefined),
  };
}
