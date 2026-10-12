// SPDX-License-Identifier: AGPL-3.0-or-later
// shots mode: each card state screenshotted in light and dark into docs/screens.
import { execFileSync } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { CARDS, root } from "./card-states-harness.mjs";
import { fixtures, nameOf } from "./card-states-fixtures.mjs";

// A palette PNG keeps flat UI screenshots small; without pngquant the full-colour file stays.
const shrink = (file) => {
  try {
    execFileSync("pngquant", ["--force", "--skip-if-larger", "--quality", "70-95", "--output", file, file], { stdio: "ignore" });
  } catch {}
};

export async function shots({ open }, { which, only, schemes }) {
  const failures = [];
  for (const cardName of which === "both" ? ["python", "react"] : [which]) {
    // The React card shows a refusal only as the reply to its own tools/call, so a pushed refusal is not its state.
    for (const key of Object.keys(fixtures).sort().filter((k) => only.test(k) && !(cardName === "react" && fixtures[k].notice))) {
      for (const scheme of cardName === "react" ? ["light"] : schemes) {
        const file = `${root}docs/screens/${CARDS[cardName].prefix}-${nameOf(key)}-${scheme}.png`;
        const { page, context, errors } = await open(cardName, key, scheme);
        const height = await page.evaluate(() => window.__height);
        const png = await page.locator("#card").screenshot();
        await writeFile(file, png);
        shrink(file);
        const blank = await page.frameLocator("#card").locator("body").innerText();
        console.log(`${cardName.padEnd(6)} ${key.padEnd(24)} ${scheme.padEnd(5)} ${String(height).padStart(4)}px ${String(Math.round(png.length / 1024)).padStart(3)} KB ${blank.trim() ? "" : "BLANK "}${errors.join("; ")}`);
        if (!blank.trim() || errors.length) failures.push(`${cardName} ${key} ${scheme}`);
        await context.close();
      }
    }
  }
  return failures;
}
