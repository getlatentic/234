// SPDX-License-Identifier: AGPL-3.0-or-later
// Shows each card state in a sandboxed iframe on the official AppBridge and, per mode:
//   shots   screenshots the card in light and dark into docs/screens (card-<connector>-<state>-<scheme>.png,
//           react-<connector>-<state>-<scheme>.png for the unchanged React card)
//   checks  interaction, accessibility and contrast checks of the Python-side card
//   live    the card against running Workers: checkout, one-time code, payouts refused, order tracker
//           (PLAIN/OTP/NOPAY urls as in card-states-capture.mjs; PLAIN needs a small FOOD_STEP_SECONDS)
//
// usage: node conformance/card-states.mjs shots|checks|live [--card python|react|both] [--only <regex>] [--schemes light,dark]
// The QuoteViews are the ones recorded by card-states-capture.mjs (card-states.fixtures.json); a few
// states that need a hostile input (a long name) or a clock (a transfer in flight) are derived from them below.
import { checks } from "./card-states-checks.mjs";
import { startHarness } from "./card-states-harness.mjs";
import { live } from "./card-states-live.mjs";
import { addFailures, failures } from "./card-states-report.mjs";
import { shots } from "./card-states-shots.mjs";

const PORT = Number(process.env.STATES_PORT ?? 8893);
const args = process.argv.slice(2);
const mode = args[0] ?? "shots";
const option = (name, fallback) => (args.includes(`--${name}`) ? args[args.indexOf(`--${name}`) + 1] : fallback);
const options = {
  which: option("card", mode === "checks" ? "python" : "both"),
  only: new RegExp(option("only", ".")),
  schemes: option("schemes", "light,dark").split(","),
};

const harness = await startHarness(PORT);
try {
  const run = mode === "checks" ? checks : mode === "live" ? live : shots;
  const failed = await run(harness, options);
  if (failed?.length) addFailures(failed.length);
} finally {
  await harness.close();
}
const failed = failures();
if (mode !== "shots") console.log(failed === 0 ? "\nAll checks passed." : `\n${failed} check(s) failed.`);
process.exit(failed === 0 ? 0 : 1);
