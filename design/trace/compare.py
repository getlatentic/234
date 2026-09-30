# SPDX-License-Identifier: AGPL-3.0-or-later
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy"]
# ///
"""Puts the brand SVGs beside the concept PNGs and measures how far they differ, as a contact sheet written to .internal/brand-compare.png (ignored by git: it shows the concept art).

usage: uv run design/trace/compare.py "<folder holding the eleven concept PNGs>"     (needs rsvg-convert)

Each pair is aligned by the bounding box of its ink and compared by intersection over union of the ink masks
(`logo` against the reverse board, where the 4's stem is complete, `symbol` against its own board, `lockup`
against the secondary board). The sheet shows source, drawing and the difference (red: only the source, blue: only ours).
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".internal/brand-compare.png"


def find(folder: Path, suffix: str) -> Path:
    matches = sorted(folder.glob(f"*{suffix}.png")) if folder.is_dir() else []
    if len(matches) != 1:
        sys.exit(
            f"{folder} holds {len(matches)} files matching *{suffix}.png, expected one. The eleven concept PNGs are not "
            "distributed with this repository (the traced SVGs in design/mark/ are the committed output): pass the folder "
            "that holds them, or do not run this script."
        )
    return matches[0]


def render(svg: Path, height: int) -> Image.Image:
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp, "r.png")
        subprocess.run(["rsvg-convert", "-h", str(height), str(svg), "-o", str(png)], check=True)
        return Image.open(png).convert("RGBA")


def ink(image: Image.Image, kind: str) -> np.ndarray:
    a = np.array(image.convert("RGBA")).astype(int)
    if kind == "on-white":  # a board with a transparent or white ground
        return (a[..., 3] > 128) & (a[..., :3].sum(axis=2) < 740)
    if kind == "on-green":  # the reverse board: anything unlike the field
        field = np.array([3, 73, 47])
        return np.abs(a[..., :3] - field).sum(axis=2) > 90
    raise ValueError(kind)


def crop_to(mask: np.ndarray, image: Image.Image) -> tuple[np.ndarray, Image.Image]:
    ys, xs = np.where(mask)
    box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    return mask[box[1] : box[3], box[0] : box[2]], image.crop(box)


def compare(source: Image.Image, kind: str, svg: Path, drop_plus: bool = False) -> tuple[Image.Image, Image.Image, Image.Image, float]:
    s_mask, s_img = crop_to(ink(source, kind), source.convert("RGBA"))
    ours = render(svg, s_mask.shape[0] * 2)
    o_mask, o_img = crop_to(np.array(ours)[..., 3] > 128, ours)
    o_mask = np.array(Image.fromarray(o_mask.astype("uint8") * 255).resize((s_mask.shape[1], s_mask.shape[0]), Image.BILINEAR)) > 127
    both, only_s, only_o = s_mask & o_mask, s_mask & ~o_mask, ~s_mask & o_mask
    iou = both.sum() / (both | only_s | only_o).sum()
    diff = np.full(s_mask.shape + (3,), 255, dtype="uint8")
    diff[both] = (60, 60, 60)
    diff[only_s] = (225, 40, 40)
    diff[only_o] = (40, 120, 230)
    return s_img, o_img, Image.fromarray(diff), float(iou)


def main(folder: Path) -> None:
    brand = ROOT / "design/brand"
    pairs = [
        ("symbol", find(folder, "-4"), "on-white", brand / "symbol.svg"),
        ("logo (reverse board)", find(folder, "-7"), "on-green", brand / "logo-reverse.svg"),
        ("primary logo board", find(folder, "-2"), "on-white", brand / "lockup.svg"),
    ]
    rows = []
    for name, path, kind, svg in pairs:
        src = Image.open(path)
        if kind == "on-green":
            src = src.convert("RGBA")
            background = Image.new("RGBA", src.size, (3, 73, 47, 255))
            src = Image.alpha_composite(background, src)
        s, o, d, iou = compare(src, kind, svg)
        print(f"{name}: intersection over union {iou:.4f}")
        rows.append((name, iou, [s, o, d]))
    panel = 220
    sheet = Image.new("RGB", (3 * 520 + 10, len(rows) * (panel + 34) + 10), "#f4f4f0")
    draw = ImageDraw.Draw(sheet)
    for n, (name, iou, images) in enumerate(rows):
        y = 10 + n * (panel + 34)
        draw.text((10, y), f"{name}: source, ours, difference (red: only the source, blue: only ours); intersection over union {iou:.3f}", fill="#333")
        for i, im in enumerate(images):
            scale = min(500 / im.width, panel / im.height)
            fitted = im.convert("RGBA").resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
            sheet.paste(fitted, (10 + i * 520, y + 20), fitted)
    OUT.parent.mkdir(exist_ok=True)
    sheet.save(OUT)


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser())
