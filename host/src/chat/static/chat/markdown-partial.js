// SPDX-License-Identifier: AGPL-3.0-or-later
// A reply that is still arriving, made safe to draw: `settle(text)` returns the text as it should be shown
// now, so the page never shows a marker that a later word will turn into formatting, and a block that is
// about to change shape (a table, a heading, a list) appears once, already in that shape.
//
// - a table waits for its header and delimiter row, then grows one whole row at a time
// - a line that is only `#`, `-`, `1.`, `>` or a code fence marker waits for the text after it
// - an open `**`, `*`, `_`, `~~` or backtick is closed for now; a marker with nothing after it yet waits
// - an unfinished link shows its label
// The final text is never settled: it is rendered as it is.

const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const FENCE_PREFIX = /^ {0,3}(`{1,2}|~{1,2})$/;
const LONE_MARKER = /^ {0,3}(#{1,6}|[-+*]|\d{1,9}[.)]?|>+|`{1,2}|~{1,2})$/;
const BLOCK_START = /\n(?= {0,3}(?:[-+*] |\d{1,9}[.)] |#{1,6} |>))/g;
const DELIMITER_SO_FAR = /^[\s|:-]*$/;
const DELIMITER_ROW = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
const MARKER_TAIL = /[*_~`]+$/;
const OPEN_LINK = /\[([^[\]]*)(?:\]\([^)\s]*)?$/;

const cellsOf = (row) => row.trim().replace(/^\||\|$/g, "").split("|").length;
const looksLikeRow = (line) => line.trim().startsWith("|") || (line.match(/\|/g) ?? []).length >= 2;
const isWord = (char) => char !== undefined && /[\p{L}\p{N}]/u.test(char);
const isSpace = (char) => char === undefined || /\s/.test(char);

function insideFence(lines) {
  let open = null;
  for (const line of lines) {
    const marker = FENCE.exec(line)?.[1];
    if (!marker) continue;
    if (!open) open = marker;
    else if (marker[0] === open[0] && marker.length >= open.length && line.trim() === marker) open = null;
  }
  return open !== null;
}

// The trailing lines that hold a pipe: a table that is formed (header and matching delimiter row), one that
// is about to be (a header, or a delimiter row still being typed), or not a table.
function tableTail(lines) {
  let start = lines.length;
  while (start > 0 && lines[start - 1].includes("|")) start -= 1;
  const run = lines.slice(start);
  const formed = run.length > 1 && DELIMITER_ROW.test(run[1]) && cellsOf(run[1]) === cellsOf(run[0]);
  const forming = run.length === 2 && DELIMITER_SO_FAR.test(run[1]);
  const header = run.length === 1 && looksLikeRow(run[0]);
  return { start, formed, waiting: !formed && (forming || header) };
}

function withoutPartialTable(lines) {
  const complete = lines.at(-1) === "" && lines.length > 1 && lines.at(-2).trim() !== "";
  const body = complete ? lines.slice(0, -1) : lines;
  const { start, formed, waiting } = tableTail(body);
  if (waiting) return { lines: lines.slice(0, start), table: false };
  if (!formed) return { lines, table: false };
  const partialRow = !complete && body.length - start > 2;
  return { lines: partialRow ? lines.slice(0, -1) : lines, table: true };
}

// Delimiters left open in `text`, outermost first, and the length of an open code span (0 for none).
function openDelimiters(text) {
  const stack = [];
  let code = 0;
  for (let at = 0; at < text.length; at += 1) {
    const char = text[at];
    if (char === "\\") {
      at += 1;
      continue;
    }
    const run = runLength(text, at);
    if (char === "`") code = code === 0 ? run : code === run ? 0 : code;
    else if (!code && "*_~".includes(char)) trackDelimiter(stack, text, at, run);
    at += run - 1;
  }
  return { stack, code };
}

function runLength(text, at) {
  let run = 1;
  while (text[at + run] === text[at]) run += 1;
  return run;
}

function trackDelimiter(stack, text, at, run) {
  const char = text[at];
  const before = text[at - 1];
  const after = text[at + run];
  const intraword = char === "_";
  const canOpen = !isSpace(after) && !(intraword && isWord(before));
  const canClose = !isSpace(before) && !(intraword && isWord(after));
  const kinds = char === "~" ? (run === 2 ? ["~~"] : []) : run >= 2 ? [char.repeat(2), ...(run === 3 ? [char] : [])] : [char];
  for (const kind of kinds) {
    const held = stack.lastIndexOf(kind);
    if (canClose && held !== -1) stack.length = held;
    else if (canOpen) stack.push(kind);
  }
}

function closeInline(block) {
  const trailing = /\s*$/.exec(block)[0];
  const kept = block.slice(0, block.length - trailing.length).replace(MARKER_TAIL, "");
  const { stack, code } = openDelimiters(kept);
  return kept + "`".repeat(code) + stack.reverse().join("") + trailing;
}

// Where the last paragraph, list item, heading or quote line starts: nothing inline reaches across it.
function lastBlockStart(text) {
  const blank = text.lastIndexOf("\n\n");
  const starts = [...text.matchAll(BLOCK_START)].map((found) => found.index + 1);
  return Math.max(blank === -1 ? 0 : blank + 2, starts.at(-1) ?? 0);
}

function inlineSettled(text) {
  const shown = text.replace(OPEN_LINK, "$1");
  const from = lastBlockStart(shown);
  return shown.slice(0, from) + closeInline(shown.slice(from));
}

export function settle(text) {
  const lines = text.split("\n");
  const open = lines.at(-1);
  if (insideFence(lines)) return FENCE_PREFIX.test(open) ? text.slice(0, text.length - open.length) : text;
  if (LONE_MARKER.test(open)) lines.pop();
  const { lines: shown, table } = withoutPartialTable(lines);
  const drawn = shown.join("\n");
  return table ? drawn : inlineSettled(drawn);
}
