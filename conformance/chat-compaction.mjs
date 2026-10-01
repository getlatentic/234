// SPDX-License-Identifier: AGPL-3.0-or-later
// A compacted chat as the person sees it: the history unchanged, one quiet line where the assistant's memory of
// the earlier messages was replaced by a summary (never the summary itself unless opened), only the latest
// compaction marked, the same after a reload and in a second tab, in both themes.
//
// needs the stack (tools/up.sh). usage: node conformance/chat-compaction.mjs
import { mkdirSync } from "node:fs";
import { browser, HOST, openHome, pause, say, sendFirst, settled, suite, tokenColor, watchErrors } from "./lib.mjs";

const { check, finish } = suite("Compaction");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
mkdirSync(screens, { recursive: true });
const chromium = await browser();
const errors = [];
const LINE = "Earlier messages were summarised";
const talk = (n) => `echo: message ${n}, abeg keep am short: I have been thinking about how I handle money for the shop and I want to keep things simple so I do not lose track of what I spend, and I always check twice before I send any money`;

const lines = (page) => page.locator('[data-slot="thread"] compaction-note');
const bubbles = (page) => page.locator('[data-slot="thread"] [data-kind="user"]');
const compact = (page, chat, keep = 50) =>
  page.evaluate(
    async ({ url, keep }) => {
      const token = (await (await fetch("/api/me", { credentials: "same-origin" })).json()).csrf;
      const reply = await fetch(url, { method: "POST", headers: { "X-CSRFToken": token, "content-type": "application/json" }, body: JSON.stringify({ keep_recent_tokens: keep }) });
      return reply.json();
    },
    { url: `/c/${chat}/compact`, keep },
  );
const summaryOf = async (page) => {
  await page.locator("compaction-note summary").click();
  const text = await page.locator('compaction-note [data-slot="summary"]').innerText();
  await page.locator("compaction-note summary").click();
  return text;
};

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}`);
  const context = await chromium.newContext({ colorScheme: scheme, viewport: { width: 420, height: 760 } });
  const page = await context.newPage();
  watchErrors(page, errors);
  await openHome(page);
  const chat = await sendFirst(page, talk(0));
  for (let n = 1; n < 6; n += 1) await say(page, talk(n));
  await settled(page);
  const before = await bubbles(page).count();
  check((await lines(page).count()) <= 1, "a chat that has not been compacted has no more than the one line an automatic compaction may have made");

  const made = await compact(page, chat);
  check(made.compacted === true && made.trigger === "manual", `the owner compacts the chat (${made.trigger}, ${made.tokens?.before} to ${made.tokens?.after} tokens)`);
  await lines(page).first().waitFor({ timeout: 8000 });
  check((await lines(page).count()) === 1, "the line appears in the open page, live, and there is one");
  check((await lines(page).innerText()).trim() === LINE, "it says one thing");
  check((await bubbles(page).count()) === before, "every message of the history is still on the page");
  const note = lines(page).first();
  check((await note.locator("details").evaluate((el) => el.open)) === false, "the summary is not shown until it is opened");
  check((await page.locator("body").innerText()).includes("Asked and decided") === false, "nor is any of its text on the page");
  const line = note.locator('[data-slot="line"]');
  check((await line.evaluate((el) => getComputedStyle(el).color)) === (await tokenColor(page, "ink-3")), "the line is in the quiet ink");
  check((await note.locator("summary").evaluate((el) => el.getBoundingClientRect().height)) >= 44, "and it is a target of at least 44px");
  await page.screenshot({ path: `${screens}compaction-${scheme}-1-line.png` });

  const first = await summaryOf(page);
  check(first.includes("## Asked and decided") && first.includes("message 0"), "opened, it shows what the assistant remembers");
  await note.locator("summary").click();
  await pause(150);
  await page.screenshot({ path: `${screens}compaction-${scheme}-2-open.png` });
  await note.locator("summary").click();

  await page.reload();
  check((await bubbles(page).count()) === before && (await lines(page).count()) === 1, "after a reload the history is the same and so is the one line");
  check((await lines(page).innerText()).trim() === LINE && (await summaryOf(page)) === first, "with the same summary behind it");

  const other = await context.newPage();
  watchErrors(other, errors);
  await other.goto(`${HOST}/c/${chat}/`);
  check((await lines(other).count()) === 1 && (await bubbles(other).count()) === before, "a second tab shows the same history and the same line");

  for (let n = 6; n < 11; n += 1) await say(page, talk(n));
  await settled(page);
  const again = await compact(page, chat);
  check(again.compacted === true && again.seq > made.seq, "a later compaction is written");
  await page.waitForFunction(
    (old) => document.querySelectorAll('[data-slot="thread"] compaction-note').length === 1 && document.querySelector('compaction-note [data-slot="summary"]').textContent !== old,
    first,
    { timeout: 8000 },
  );
  const second = await summaryOf(page);
  check((await lines(page).count()) === 1 && second !== first && second.includes("message 9"), "the page keeps one line, now for the latest compaction");
  await other.waitForFunction(() => document.querySelectorAll('[data-slot="thread"] compaction-note').length === 1);
  await other.waitForFunction((text) => document.querySelector('compaction-note [data-slot="summary"]').textContent === text, second, { timeout: 8000 });
  check((await bubbles(other).count()) === (await bubbles(page).count()), "the second tab follows it and agrees");
  await page.reload();
  check((await lines(page).count()) === 1 && (await summaryOf(page)) === second, "a reload shows the latest, once");
  await context.close();
}

const unexpected = errors.filter((e) => !/Failed to load resource/.test(e));
check(unexpected.length === 0, `no page errors or policy violations ${unexpected.join("; ")}`);
await chromium.close();
finish();
