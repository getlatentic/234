// SPDX-License-Identifier: AGPL-3.0-or-later
// The palette, checked without a stack: node --test conformance/palette.test.mjs
//   - the tokens are the one source: the generated files are up to date, every colour in a built stylesheet
//     is a token's, and no source writes a colour or a default Tailwind palette class of its own
//   - the palette is a decision, not a default: neutrals carry a hue in each theme, the brand is two greens
//     (the deep green as the primary, the brand greens as graphics), success is a separate teal, and
//     each brand colour is spent only where the rules say: the primary on the primary action, the focus ring
//     and a selected edge; the brand greens and mint on the mark and never as text
//   - WCAG 2.x AA for every text and control pair, in the light theme and in the dark one
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import test from "node:test";
import { parseOklch, toHex } from "../design/color.mjs";
import { GRAPHIC_ONLY, measure, measureGraphics } from "../design/contrast.mjs";
import { loadTokens } from "../design/tokens.mjs";

const root = new URL("..", import.meta.url).pathname;
const tokens = loadTokens();
const THEMES = ["light", "dark"];

function files(dir, keep) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (name === "node_modules" || name === "vendor" || name === "python_modules" || name === "generated") return [];
    if (statSync(path).isDirectory()) return files(path, keep);
    return keep(path) ? [path] : [];
  });
}

const hueDistance = (a, b) => Math.min(Math.abs(a - b) % 360, 360 - (Math.abs(a - b) % 360));

test("both themes define the same tokens", () => {
  assert.deepEqual(Object.keys(tokens.colors.light).sort(), Object.keys(tokens.colors.dark).sort());
});

for (const theme of THEMES) {
  test(`${theme}: every text and control pair reaches WCAG AA`, () => {
    const { rows, failing } = measure(tokens.colors[theme]);
    assert.ok(rows.length >= 30, "the pair list is not empty");
    assert.deepEqual(
      failing.map((r) => `${r.fg} on ${r.bg} is ${r.ratio.toFixed(2)}, needs ${r.minimum} (${r.what})`),
      [],
    );
  });

  test(`${theme}: the neutrals are tinted, not grey`, () => {
    for (const name of ["ground", "raised", "sunken", "line", "line-strong", "ink", "ink-2", "ink-3"]) {
      const { c, h } = parseOklch(tokens.colors[theme][name]);
      assert.ok(c >= 0.002, `${name} has chroma ${c}`);
      assert.ok(hueDistance(h, tokens.hue.neutral[theme]) <= 12, `${name} has hue ${h}, the ${theme} neutral hue is ${tokens.hue.neutral[theme]}`);
    }
  });

  test(`${theme}: the ground and the surfaces step in lightness so a card reads against the page`, () => {
    const l = (name) => parseOklch(tokens.colors[theme][name]).l;
    assert.notEqual(l("ground"), l("raised"));
    assert.notEqual(l("ground"), l("sunken"));
    assert.ok(Math.abs(l("raised") - l("sunken")) >= 0.02);
  });
}

test("the brand is two greens and success is a third colour apart from both", () => {
  for (const theme of THEMES) {
    const c = tokens.colors[theme];
    for (const name of ["primary", "primary-hover", "primary-pressed"]) {
      assert.ok(hueDistance(parseOklch(c[name]).h, tokens.hue.primary) <= 8, `${theme}: ${name} keeps the primary hue`);
    }
    const accent = parseOklch(c.accent);
    assert.ok(hueDistance(accent.h, tokens.hue.accent) <= 5, `${theme}: the accent keeps its hue`);
    assert.ok(accent.c >= 0.17, `${theme}: the accent is vivid (chroma ${accent.c})`);
    assert.ok(parseOklch(c.primary).c < accent.c, `${theme}: the primary is the deeper, calmer green`);
    for (const success of ["ok", "ok-soft"]) {
      const { h } = parseOklch(c[success]);
      for (const brand of ["primary", "accent", "mint"]) {
        const d = hueDistance(h, parseOklch(c[brand]).h);
        assert.ok(d >= 30, `${theme}: ${success} (hue ${h}) is ${d} degrees from ${brand}; success must not read as brand`);
      }
    }
    for (const status of ["warn", "bad"]) {
      const { h } = parseOklch(c[status]);
      for (const brand of ["primary", "accent"]) {
        assert.ok(hueDistance(h, parseOklch(c[brand]).h) >= 60, `${theme}: ${status} is far from ${brand}`);
      }
    }
  }
});

test("the deep green is the primary: white on it and it on the ground both pass AA; the brand greens as text fail, with the numbers", () => {
  const light = measure(tokens.colors.light).rows;
  const ratio = (fg, bg) => light.find((r) => r.fg === fg && r.bg === bg).ratio;
  assert.ok(ratio("on-primary", "primary") >= 9, `white on the deep green is ${ratio("on-primary", "primary").toFixed(2)}:1`);
  assert.ok(ratio("primary", "ground") >= 9, `the deep green on the warm ground is ${ratio("primary", "ground").toFixed(2)}:1`);
  const graphics = measureGraphics(tokens.brand);
  assert.equal(graphics.length, GRAPHIC_ONLY.length);
  for (const { name, hex, ratios } of graphics) {
    for (const [ground, value] of Object.entries(ratios)) assert.ok(value < 3.05, `${name} ${hex} on ${ground} is ${value.toFixed(2)}:1: it may never be text (4.5) and does not even reach 3`);
  }
});

test("the check has teeth: the vivid green as the primary fails the label, and a success colour in the brand hue fails the separation", () => {
  const light = { ...tokens.colors.light, primary: tokens.colors.light.accent };
  const failing = measure(light).failing.map((r) => `${r.fg} on ${r.bg}`);
  assert.ok(failing.includes("on-primary on primary"), `failing: ${failing}`);
  assert.ok(hueDistance(parseOklch("oklch(44% .085 159)").h, parseOklch(tokens.colors.light.primary).h) < 30);
});

test("the generated files are up to date with tokens.json", () => {
  execFileSync("node", [`${root}design/build.mjs`, "--check"], { stdio: "pipe" });
});

const SOURCES = [
  ...files(`${root}host/src`, (p) => /\.(html|js|py|css)$/.test(p)),
  ...files(`${root}host/web`, (p) => p.endsWith(".css")),
  ...files(`${root}card`, (p) => /\.(html|js|css|py)$/.test(p)),
  ...files(`${root}checkout/src`, (p) => /\.py$/.test(p)),
  `${root}design/components.css`,
].filter((p) => !p.endsWith("palette.py") && !p.endsWith("tokens_css.py") && !p.endsWith("host-styles.js") && !/checkout\/src\/checkout\/card\//.test(p) && !p.endsWith("turns/reach/card.html"));
const rel = (p) => relative(root, p);

test("no source writes a colour: colours come from the tokens", () => {
  const literal = /oklch\(|\brgba?\(|\bhsla?\(|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{8}\b/;
  const found = SOURCES.filter((p) => literal.test(readFileSync(p, "utf8"))).map(rel);
  assert.deepEqual(found, []);
});

test("no source uses a default Tailwind palette class", () => {
  const palette = /\b(?:bg|text|border|outline|ring|fill|stroke|divide|accent|from|to|via|decoration|caret|placeholder|marker)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|white|black)(?:-\d+)?\b/;
  const found = SOURCES.filter((p) => palette.test(readFileSync(p, "utf8"))).map(rel);
  assert.deepEqual(found, []);
});

test("the primary is spent on the primary action, the focus ring and a selected edge, nowhere else", () => {
  const token = /[\w:[\]().*&>-]*\b(?:bg|text|border|outline|ring|fill|stroke|decoration|caret|divide|accent)-(?:on-)?primary(?:-hover|-pressed)?\b/g;
  const isFocus = (t) => /focus/.test(t);
  const isSelection = (t) => /^aria-pressed:border-primary$/.test(t);
  const isAction = (t, path) => /^(?:bg-primary|hover:bg-primary-hover|active:bg-primary-pressed|text-on-primary)$/.test(t) && /components\.css$|chat\.html$/.test(path);
  const misused = [];
  for (const path of SOURCES.filter((p) => /\.(html|js|css)$/.test(p))) {
    const text = readFileSync(path, "utf8").replaceAll(/var\(--[\w-]+\)/g, "");
    for (const [t] of text.matchAll(token)) {
      if (!isFocus(t) && !isSelection(t) && !isAction(t, path)) misused.push(`${rel(path)}: ${t}`);
    }
  }
  assert.deepEqual([...new Set(misused)], []);
  const page = readFileSync(`${root}checkout/src/checkout/sim_checkout_page.py`, "utf8");
  const primaryLines = page.split("\n").filter((l) => /var\(--primary|var\(--on-primary/.test(l));
  assert.ok(primaryLines.length >= 3, "the checkout page's primary button and focus ring use the primary tokens");
  for (const line of primaryLines) assert.match(line, /\.primary|focus-visible|hover/, `the checkout page spends the primary on: ${line.trim()}`);
  assert.doesNotMatch(page, /--accent|--on-accent/, "the checkout page has no accent");
});

test("the brand greens are a graphic: they are on the wordmark and never text", () => {
  const token = /[\w:[\]().*&>-]*\b(?:bg|text|border|outline|ring|fill|stroke|decoration|caret|divide|accent|placeholder|from|to|via)-(?:accent|mark-mint|mark)\b/g;
  const found = [];
  for (const path of SOURCES.filter((p) => /\.(html|js|css)$/.test(p))) {
    const text = readFileSync(path, "utf8").replaceAll(/var\(--[\w-]+\)/g, "");
    for (const [t] of text.matchAll(token)) found.push(`${rel(path)}: ${t}`);
  }
  assert.deepEqual(
    [...new Set(found)].sort(),
    ["fill-accent", "fill-mark", "fill-mark-mint"].map((t) => `host/src/chat/templates/chat/_wordmark.html: ${t}`),
  );
  for (const path of [`${root}checkout/src/checkout/sim_checkout_page.py`, ...SOURCES.filter((p) => /\.(html|js|css)$/.test(p))]) {
    assert.doesNotMatch(readFileSync(path, "utf8").replaceAll(/fill-(?:accent|mark-mint|mark)/g, ""), /var\(--(?:accent|mark|mark-mint)\)|color:\s*var\(--(?:accent|mark)/, `${rel(path)} draws text in a brand graphic colour`);
  }
});

test("every colour in a built stylesheet is a token's", () => {
  const known = new Set(THEMES.flatMap((t) => Object.values(tokens.colors[t]).map((v) => toHex(v).toLowerCase())));
  const built = [
    `${root}host/build/app.css`,
    `${root}checkout/src/checkout/card/card.html`,
    `${root}checkout/src/checkout/card/menu.html`,
    `${root}checkout/src/checkout/card/memory.html`,
    `${root}host/src/turns/reach/card.html`,
    `${root}checkout/src/checkout/tokens_css.py`,
  ];
  if (!existsSync(built[0])) execFileSync("node", [`${root}host/build.mjs`], { stdio: "pipe" });
  const sim = readFileSync(`${root}checkout/src/checkout/sim_checkout_page.py`, "utf8");
  assert.doesNotMatch(sim, /#[0-9a-fA-F]{6}/, "the checkout page's own CSS writes no colour");
  for (const path of built) {
    const strays = [...readFileSync(path, "utf8").matchAll(/#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?\b/g)]
      .map(([hex]) => hex.toLowerCase())
      .filter((hex) => !known.has(hex));
    assert.deepEqual([...new Set(strays)], [], `${rel(path)} has colours that are not tokens`);
  }
});
