// SPDX-License-Identifier: AGPL-3.0-or-later
// A reply is Markdown, drawn by one renderer whether it streams or comes from history, and nothing in it can
// run: real streams through the model, the hostile texts in the real page under its real policy, a check that
// each of them fails when its safeguard is taken out, the once-per-frame rule, and a phone's layout.
//
// needs the stack (tools/up.sh). usage: node conformance/chat-markdown.mjs
import { readFileSync, mkdirSync } from "node:fs";
import { browser, HOST, openHome, sendFirst, suite, watchErrors } from "./lib.mjs";
import { HOSTILE, LONG_WORD, SAMPLE, findings } from "./markdown-fixtures.mjs";

const { check, finish } = suite("Markdown in the chat");
const screens = new URL("../docs/screens/", import.meta.url).pathname;
const moduleSource = readFileSync(new URL("../host/src/chat/static/chat/markdown.js", import.meta.url), "utf8");
mkdirSync(screens, { recursive: true });
const chromium = await browser();
const errors = [];
const echo = (markdown) => `echo: ${markdown.replaceAll("\n", "\\n")}`;
const idle = (page) =>
  page.waitForFunction(() => document.querySelector("[data-message]") && !document.querySelector("chat-thread").hasAttribute("data-working"), null, { timeout: 30000 });
const lastReply = (page) => page.locator("assistant-text").last();

/** In the page: render every text in its own element and report what is wrong with any of them. */
const matrix = (page, texts) =>
  page.evaluate(
    async ({ checker, texts }) => {
      const findingsOf = new Function(`return ${checker}`)();
      window.__pwned = 0;
      const out = [];
      for (const text of texts) {
        const el = document.createElement("assistant-text");
        el.className = "flex max-w-prose flex-col gap-2";
        document.body.append(el);
        el.finish(text);
        el.render();
        await new Promise((done) => requestAnimationFrame(() => setTimeout(done, 30)));
        const bad = findingsOf(el);
        if (bad.length) out.push({ text: text.slice(0, 60), bad });
        el.remove();
      }
      return out;
    },
    { checker: findings.toString(), texts },
  );

const phone = (scheme, width = 420, height = 800) => chromium.newContext({ colorScheme: scheme, viewport: { width, height } });

for (const scheme of ["light", "dark"]) {
  console.log(`\n${scheme}: a reply that streams`);
  const context = await phone(scheme);
  const page = await context.newPage();
  watchErrors(page, errors);
  await openHome(page);
  await page.evaluate(() => {
    window.__frames = [];
    new MutationObserver(() => {
      const el = [...document.querySelectorAll("assistant-text")].at(-1);
      if (el) window.__frames.push({ blocks: [...el.children].map((c) => c.outerHTML), text: el.innerText });
    }).observe(document.querySelector('[data-slot="thread"]'), { childList: true, subtree: true, characterData: true });
  });
  await sendFirst(page, echo(SAMPLE));
  await lastReply(page).locator("table").waitFor({ timeout: 25000 });
  await page.waitForFunction(() => document.querySelector("assistant-text pre") !== null && document.body.innerText.includes("Done."), null, { timeout: 25000 });
  await idle(page);
  const reply = lastReply(page);
  check((await reply.locator("h1").innerText()) === "Plan", "the heading is a heading");
  check((await reply.locator("strong").allInnerTexts()).join() === "the summary,item", "bold is bold");
  check((await reply.locator("em").innerText()) === "emphasis" && (await reply.locator("s").innerText()) === "old", "italic and strikethrough");
  check((await reply.locator("li").count()) === 4 && (await reply.locator("ol li").count()) === 2, "the lists are lists");
  check((await reply.locator("pre code").innerText()).includes("const total = 2 * 3;"), "the code is a code block");
  const link = reply.locator("a");
  check((await link.getAttribute("href")) === "https://example.com/docs" && (await link.getAttribute("target")) === "_blank" && (await link.getAttribute("rel")) === "noopener noreferrer", "the link opens in a new tab with rel noopener noreferrer");
  check((await reply.locator("table td").first().evaluate((td) => getComputedStyle(td).fontVariantNumeric)).includes("tabular-nums"), "table numbers are tabular");
  check(!(await reply.innerText()).match(/\*\*|~~|\]\(|^\|/m), "no raw markers show in the finished reply");
  const frames = await page.evaluate(() => window.__frames);
  const drawn = frames.filter((f, i) => i === 0 || f.text !== frames[i - 1].text);
  check(drawn.length >= 8, `it streamed in pieces (${drawn.length} distinct states)`);
  check(drawn.every((f) => !/\*\*|~~|\]\(|^\||`{2}/m.test(f.text)), "in no state of the stream does a raw marker show (** ~~ ]( a pipe row or a fence)");
  let jumps = 0;
  for (let i = 1; i < frames.length; i += 1) {
    const before = frames[i - 1].blocks;
    const after = frames[i].blocks;
    if (after.length < before.length - 1 || !before.slice(0, -1).every((b, n) => after[n] === b)) jumps += 1;
  }
  check(jumps === 0, `only the last block changes from one state to the next (${jumps} exceptions in ${frames.length} states)`);
  const live = await reply.innerHTML();
  await page.screenshot({ path: `${screens}markdown-${scheme}.png` });
  await page.reload();
  check((await lastReply(page).innerHTML()) === live, "after a reload the stored reply is the same markup as the streamed one");
  const mine = await page.locator(".self-end").first().innerHTML();
  check(!/<strong|<em|<table/.test(mine) && mine.includes("**the summary**"), "the person's own message stays plain text");

  console.log(`\n${scheme}: hostile replies through the model`);
  await openHome(page);
  await sendFirst(page, echo(`<script>window.__pwned=1</script> <img src=x onerror=window.__pwned=1> [a](javascript:window.__pwned=1) [b](https://example.com/ok) ![i](https://evil.example/t.png)`));
  await page.waitForFunction(() => document.querySelector("assistant-text a") !== null, null, { timeout: 20000 });
  await idle(page);
  check(await page.evaluate(({ checker }) => new Function(`return ${checker}`)()(document.querySelector("assistant-text")).length === 0, { checker: findings.toString() }), "no element, attribute, link or script from it");
  check((await lastReply(page).innerText()).includes("<script>window.__pwned=1</script>"), "the text is shown as text");
  await openHome(page);
  await sendFirst(page, echo("| a | b |\n|---|---|\n| <img src=x onerror=window.__pwned=1> | <b>x</b> |\n| [x](javascript:window.__pwned=1) | ok |"));
  await page.waitForFunction(() => document.querySelector("assistant-text tbody tr:last-child td:last-child")?.textContent.includes("ok"), null, { timeout: 20000 });
  await idle(page);
  check(await page.evaluate(({ checker }) => new Function(`return ${checker}`)()(document.querySelector("assistant-text")).length === 0, { checker: findings.toString() }), "nor from a table cell");
  await context.close();
}

console.log("\nevery hostile text, in the real page under its policy");
{
  const context = await phone("light");
  const page = await context.newPage();
  watchErrors(page, errors);
  await openHome(page);
  const bad = await matrix(page, [...HOSTILE, LONG_WORD, "[ok](https://example.com/a?b=1&c=2) and [mail](mailto:a@example.com)"]);
  check(bad.length === 0, `${HOSTILE.length} hostile texts leave nothing behind ${JSON.stringify(bad).slice(0, 300)}`);
  const good = await matrix(page, ["[ok](https://example.com/a?b=1&c=2)"]);
  const href = await page.evaluate(async () => {
    const el = document.createElement("assistant-text");
    document.body.append(el);
    el.finish("[ok](https://example.com/a?b=1&c=2)");
    el.render();
    return el.querySelector("a")?.href;
  });
  check(good.length === 0 && href === "https://example.com/a?b=1&c=2", "a good link is kept exactly");
  await context.close();
}

console.log("\nthe same texts with one safeguard taken out: the checks must fail");
const mutations = [
  ["raw HTML allowed", (s) => s.replace("markdownit({ html: false", "markdownit({ html: true")],
  ["links not validated", (s) => s.replace("md.validateLink = (url) => SAFE_LINK.test(url.trim());", "md.validateLink = () => true;")],
  ["images allowed", (s) => s.replace('md.disable("image");', "")],
  ["links without target and rel", (s) => s.replace('token.attrSet("target", "_blank");', "").replace('token.attrSet("rel", "noopener noreferrer");', "")],
];
for (const [name, change] of mutations) {
  const changed = change(moduleSource);
  check(changed !== moduleSource, `the mutation "${name}" changes the module`);
  const context = await phone("light");
  await context.route("**/static/chat/markdown.js", (route) => route.fulfill({ contentType: "text/javascript", body: changed }));
  const page = await context.newPage();
  await openHome(page);
  const bad = await matrix(page, [...HOSTILE, "[ok](https://example.com/a)"]);
  check(bad.length > 0, `with ${name}, ${bad.length} of the texts are caught`);
  await context.close();
}

console.log("\none render per animation frame");
{
  const context = await phone("light");
  const page = await context.newPage();
  await openHome(page);
  const result = await page.evaluate(async () => {
    const el = document.createElement("assistant-text");
    document.body.append(el);
    let renders = 0;
    new MutationObserver(() => (renders += 1)).observe(el, { childList: true });
    for (let i = 0; i < 300; i += 1) el.stream(`word${i} `);
    await new Promise((done) => setTimeout(done, 100));
    const afterFirstBurst = renders;
    el.stream("last ");
    el.stream("one ");
    await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
    return { afterFirstBurst, renders, words: el.innerText.trim().split(/\s+/).length };
  });
  check(result.afterFirstBurst === 1, `300 changes in one task draw once (${result.afterFirstBurst})`);
  check(result.renders === 2 && result.words === 302, "a later burst draws once more, with everything so far");
  await context.close();
}

console.log("\na phone: a wide table and a long word");
for (const scheme of ["light", "dark"]) {
  const context = await phone(scheme, 320, 568);
  const page = await context.newPage();
  watchErrors(page, errors);
  await openHome(page);
  await sendFirst(page, echo("| Item | Qty | Unit price | Total | Note |\n|:--|--:|--:|--:|:--|\n| Jollof rice | 2 | 1,200 | 2,400 | with plantain |\n| Beans | 12 | 950 | 11,400 | no pepper |"));
  await page.waitForFunction(() => document.querySelectorAll("assistant-text tbody tr").length === 2, null, { timeout: 25000 });
  await idle(page);
  const table = await page.evaluate(() => {
    const wrapper = document.querySelector("assistant-text .overflow-x-auto");
    return { scrolls: wrapper.scrollWidth > wrapper.clientWidth, overflow: getComputedStyle(wrapper).overflowX, page: document.documentElement.scrollWidth <= innerWidth };
  });
  check(table.scrolls && table.overflow === "auto" && table.page, "a table wider than the phone scrolls inside the bubble, not the page");
  await page.screenshot({ path: `${screens}markdown-${scheme}-320-table.png` });
  await page.reload();
  await page.waitForFunction(() => document.querySelectorAll("assistant-text tbody tr").length === 2);
  const faces = await page.evaluate(() => ({ loaded: [...document.fonts].filter((face) => face.status === "loaded").map((face) => face.family), heading: Boolean(document.querySelector("assistant-text h1, assistant-text h2, assistant-text h3")) }));
  check(faces.loaded.length === (faces.heading ? 1 : 0) && faces.loaded.every((family) => family === "Manrope"), `a conversation opened fresh loads a web font only for a heading, and then only Manrope (${JSON.stringify(faces)})`);
  await openHome(page);
  await sendFirst(page, echo("## Your order\n\nIt is on its way."));
  await page.waitForFunction(() => document.querySelector("assistant-text h2") && document.querySelector("assistant-text")?.textContent.includes("on its way"), null, { timeout: 20000 });
  await idle(page);
  await page.evaluate(() => document.fonts.ready);
  const heading = await page.evaluate(() => ({ family: getComputedStyle(document.querySelector("assistant-text h2")).fontFamily, body: getComputedStyle(document.querySelector("assistant-text p")).fontFamily, loaded: [...document.fonts].filter((face) => face.status === "loaded").map((face) => `${face.family} ${face.weight}`) }));
  check(heading.family.startsWith("Manrope") && !heading.body.startsWith("Manrope") && heading.loaded.length === 1 && heading.loaded[0].startsWith("Manrope"), `a heading is set in Manrope, loaded from the Worker's static files, and the text under it in the system stack (${JSON.stringify(heading)})`);
  await openHome(page);
  await sendFirst(page, echo(`${LONG_WORD} then some words`));
  await page.waitForFunction(() => document.querySelector("assistant-text")?.textContent.includes("some words"), null, { timeout: 20000 });
  await idle(page);
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "a word of 400 letters wraps and the page does not scroll sideways");
  await context.close();
}

check(errors.length === 0, `no page errors or policy violations ${errors.join("; ")}`);
await chromium.close();
finish();
