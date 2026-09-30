// SPDX-License-Identifier: AGPL-3.0-or-later
// The menu card behind the official ext-apps AppBridge, in Chromium: rows and drawings, Add and the
// stepper, the cart, search and categories, full screen through the display-mode API, pictures and the
// sandbox policy, contrast, a card 320 px wide, a menu of 300 items, the order it sends (ids, quantities
// and an area, nothing priced), and the keyboard. It writes the light and dark screenshots into
// docs/screens/ (menu-<state>-<scheme>.png).
//
// The menu and the card page come from the running connector Worker (tools/up.sh), read through the
// protocol as a host reads them. usage: node conformance/menu-card.mjs [section]
import { suite } from "./lib.mjs";
import { startHarness } from "./menu-card/harness.mjs";
import { bigList, contrastAndNames, narrowCard } from "./menu-card/layout.mjs";
import { fullScreen, pictures } from "./menu-card/modes.mjs";
import { keyboard, ordering } from "./menu-card/order.mjs";
import { rowsAndCart, searchAndChips } from "./menu-card/rows.mjs";

const { check, finish } = suite("Menu card");
const only = process.argv[2] ?? "";
const sections = { rowsAndCart, searchAndChips, fullScreen, pictures, ordering, contrastAndNames, narrowCard, bigList, keyboard };
const h = await startHarness();
try {
  for (const scheme of ["light", "dark"]) {
    for (const [name, run] of Object.entries(sections)) if (name.toLowerCase().includes(only.toLowerCase())) await run(h, check, scheme);
  }
} finally {
  await h.close();
}
finish();
