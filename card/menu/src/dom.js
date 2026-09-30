// SPDX-License-Identifier: AGPL-3.0-or-later
export const fromTemplate = (id) => document.getElementById(id).content.firstElementChild.cloneNode(true);

export const slot = (node, name) => (node.dataset.slot === name ? node : node.querySelector(`[data-slot="${name}"]`));

export const show = (node, visible) => node.toggleAttribute("hidden", !visible);

export function setText(node, name, text) {
  const target = slot(node, name);
  target.textContent = text ?? "";
  show(target, Boolean(text));
}
