// SPDX-License-Identifier: AGPL-3.0-or-later
// The Tailwind classes of everything Markdown produces. They are written out here, in a file the stylesheet
// build scans, so the CSS holds exactly these and the page needs no rules of its own.
const code = "bg-sunken font-mono text-sm";
const cell = "min-w-24 px-3 py-1.5 align-top";

export const CLASSES = {
  paragraph_open: "m-0",
  heading_open: { h1: "m-0 font-display text-lg font-bold", h2: "m-0 font-display text-base font-bold", default: "m-0 font-display font-bold" },
  bullet_list_open: "m-0 flex list-disc flex-col gap-1.5 pl-5 marker:text-ink-3",
  ordered_list_open: "m-0 flex list-decimal flex-col gap-1.5 pl-5 marker:text-ink-3",
  list_item_open: "pl-0.5",
  blockquote_open: "m-0 border-l-2 border-line-strong pl-3 text-ink-2",
  hr: "m-0 border-line-strong",
  code_inline: `rounded-sm px-1 ${code}`,
  link_open: "text-ink underline decoration-ink-3 underline-offset-2 hover:decoration-ink",
  table_open: "w-full border-collapse text-left text-sm tabular-nums",
  th_open: `${cell} border-b border-line-strong font-semibold`,
  td_open: `${cell} border-b border-line`,
};

export const SCROLLER = "overflow-x-auto";
export const CODE_BLOCK = `m-0 overflow-x-auto rounded-control p-3 ${code}`;

export const ALIGNED = { left: "text-left", center: "text-center", right: "text-right" };
