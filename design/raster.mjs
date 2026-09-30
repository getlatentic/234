// SPDX-License-Identifier: AGPL-3.0-or-later
// Rasterises the icons' SVG sources (written by design/build.mjs) into the PNGs and the .ico the page and the
// manifest name, with Chromium, and a contact sheet of them at the sizes they are shipped:
// node design/raster.mjs. The PNGs are committed; run this after the mark or the tile colour changes.
import { readFileSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";

const root = new URL("..", import.meta.url).pathname;
const dir = `${root}host/src/chat/static/chat/brand/`;
const svg = (name) => readFileSync(`${dir}${name}`, "utf8");

const PNGS = [
  ["apple-touch-icon.png", "icon-maskable.svg", 180],
  ["icon-192.png", "icon.svg", 192],
  ["icon-512.png", "icon.svg", 512],
  ["icon-maskable-512.png", "icon-maskable.svg", 512],
];
const ICO_SIZES = [16, 32, 48];

async function render(page, source, size) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:${size}px;height:${size}px}</style>${source}`);
  return page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
}

/** A .ico that holds PNG images, which every current browser reads. */
function ico(images) {
  const head = Buffer.alloc(6 + 16 * images.length);
  head.writeUInt16LE(1, 2);
  head.writeUInt16LE(images.length, 4);
  let offset = head.length;
  images.forEach(({ size, png }, i) => {
    const at = 6 + 16 * i;
    head.writeUInt8(size, at);
    head.writeUInt8(size, at + 1);
    head.writeUInt16LE(1, at + 4);
    head.writeUInt16LE(32, at + 6);
    head.writeUInt32LE(png.length, at + 8);
    head.writeUInt32LE(offset, at + 12);
    offset += png.length;
  });
  return Buffer.concat([head, ...images.map(({ png }) => png)]);
}

const SHEET = `${root}docs/screens/brand-icons.png`;
const uri = (png) => `data:image/png;base64,${png.toString("base64")}`;

/** The icons as shipped, on the two grounds they meet; the small ones magnified; the maskable icon under a circle mask. */
async function contactSheet(page) {
  const shipped = [
    [16, "favicon.svg"], [32, "favicon.svg"], [48, "favicon.svg"],
    [180, "icon-maskable.svg"], [192, "icon.svg"], [512, "icon.svg"],
  ];
  const sized = [];
  for (const [size, file] of shipped) sized.push([size, uri(await render(page, svg(file), size))]);
  const depth = uri(await render(page, readFileSync(`${root}design/brand/app-icon-depth.svg`, "utf8"), 192));
  const maskable = uri(await render(page, svg("icon-maskable.svg"), 192));
  const tile = ([size, data]) => `<figure><img src="${data}" width="${Math.min(size, 192)}" height="${Math.min(size, 192)}"><figcaption>${size}</figcaption></figure>`;
  const magnified = ([size, data]) => `<figure><img class="m" src="${data}" style="width:${size * 8}px"><figcaption>${size} at 8x</figcaption></figure>`;
  const grounds = ["#faf8f2", "#08120c"]
    .map((ground, i) => `<section style="background:${ground};color:${i ? "#afc4b5" : "#535046"}">${sized.map(tile).join("")}</section>`)
    .join("");
  const extra = `<section style="background:#faf8f2;color:#535046">${sized.slice(0, 2).map(magnified).join("")}<figure><img src="${maskable}" width="192" height="192" style="border-radius:50%"><figcaption>maskable under a circle</figcaption></figure><figure><img src="${depth}" width="192" height="192"><figcaption>depth version at 192 (not shipped)</figcaption></figure></section>`;
  const html = `<style>body{margin:0;font:12px system-ui}section{display:flex;gap:28px;align-items:flex-end;padding:24px}figure{margin:0}figcaption{margin-top:6px}.m{image-rendering:pixelated}</style>${grounds}${extra}`;
  await page.setViewportSize({ width: 1240, height: 900 });
  await page.setContent(html);
  await page.screenshot({ path: SHEET, fullPage: true });
}

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });
for (const [file, source, size] of PNGS) writeFileSync(`${dir}${file}`, await render(page, svg(source), size));
const images = [];
for (const size of ICO_SIZES) images.push({ size, png: await render(page, svg("favicon.svg"), size) });
writeFileSync(`${dir}favicon.ico`, ico(images));
await contactSheet(page);
await browser.close();
