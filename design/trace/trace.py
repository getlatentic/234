# SPDX-License-Identifier: AGPL-3.0-or-later
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "numpy"]
# ///
"""Vectorises the concept "234" and "Ask" lettering into design/mark/*.svg, once, offline.

usage: uv run design/trace/trace.py "<folder holding the eleven concept PNGs>"     (needs `potrace` on PATH)

The sources are raster concept art. The numerals are traced from the reverse version (white on deep green:
the crispest, `...-7.png`) with the 4's stem completed where the plus covers it, and 'Ask' from the secondary
lockup (`...-2.png`, transparent ground). Steps: threshold, close the hairline gaps the drawing leaves where
glyphs overlap, potrace, then fit.py (corner-to-corner Beziers, axis-snapped lines). The result is checked
against the source mask and its intersection over union is printed. Only the SVG outputs are committed.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from fit import fit_path, parse_potrace, snap, to_d
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "mark"
CLOSE = 5  # pixels: fuses the keyline the drawing leaves between overlapping glyphs


def find(folder: Path, suffix: str) -> Path:
    matches = sorted(folder.glob(f"*{suffix}.png")) if folder.is_dir() else []
    if len(matches) != 1:
        sys.exit(
            f"{folder} holds {len(matches)} files matching *{suffix}.png, expected one. The eleven concept PNGs are not "
            "distributed with this repository (the traced SVGs in design/mark/ are the committed output): pass the folder "
            "that holds them, or do not run this script."
        )
    return matches[0]


def numerals_mask(source: Path) -> Image.Image:
    grey = np.array(Image.open(source).convert("L")).astype(float)
    grey[280:540, 1055:1275] = 0  # the plus
    grey[378:540, 1054:1167] = 255  # the 4's stem, which the plus covers
    return Image.fromarray(grey.astype("uint8")).point(lambda v: 255 if v > 150 else 0)


def ask_mask(source: Path) -> Image.Image:
    alpha = Image.open(source).convert("RGBA").getchannel("A")
    box = Image.new("L", alpha.size, 0)
    ImageDraw.Draw(box).rectangle((215, 735, 695, 940), fill=255)
    return Image.fromarray(np.minimum(np.array(alpha), np.array(box))).point(lambda v: 255 if v > 128 else 0)


def close(mask: Image.Image) -> Image.Image:
    return mask.filter(ImageFilter.MaxFilter(CLOSE)).filter(ImageFilter.MinFilter(CLOSE))


def potrace(mask: Image.Image) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        pbm, svg = Path(tmp, "m.pbm"), Path(tmp, "m.svg")
        Image.fromarray(np.array(mask) == 0).convert("1").save(pbm)
        subprocess.run(
            ["potrace", str(pbm), "-b", "svg", "-u", "1", "--flat", "-t", "50", "-a", "1.0", "-O", "1.0", "-o", str(svg)],
            check=True,
        )
        return svg.read_text()


def render(d: str, size: tuple[int, int], origin: tuple[float, float]) -> np.ndarray:
    """The outline rasterised by rsvg-convert, as a boolean mask in the source's own coordinates."""
    with tempfile.TemporaryDirectory() as tmp:
        svg, png = Path(tmp, "r.svg"), Path(tmp, "r.png")
        svg.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size[0]}" height="{size[1]}" viewBox="0 0 {size[0]} {size[1]}">'
            f'<rect width="100%" height="100%" fill="#000"/><g transform="translate({origin[0]} {origin[1]})">'
            f'<path d="{d}" fill="#fff" fill-rule="evenodd"/></g></svg>'
        )
        subprocess.run(["rsvg-convert", str(svg), "-o", str(png)], check=True)
        return np.array(Image.open(png).convert("L")) > 127


def trace(name: str, mask: Image.Image, title: str, folder_note: str) -> None:
    fused = close(mask)
    paths = snap([fit_path(p) for p in parse_potrace(potrace(fused), mask.height)])
    ys, xs = np.where(np.array(fused) > 0)
    origin = (float(xs.min()), float(ys.min()))
    box = (float(xs.max() - xs.min() + 1), float(ys.max() - ys.min() + 1))
    d = "".join(to_d(p, origin) for p in paths)
    nodes = sum(len(p) for p in paths)
    overlap = render(d, mask.size, origin)
    want = np.array(fused) > 0
    iou = (overlap & want).sum() / (overlap | want).sum()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {box[0]:g} {box[1]:g}">\n<title>{title}</title>\n'
        f"<!-- {folder_note} Traced by design/trace/trace.py; {nodes} nodes. -->\n"
        f'<path fill-rule="evenodd" d="{d}"/>\n</svg>\n'
    )
    print(f"{name}: {nodes} nodes, {box[0]:g} x {box[1]:g}, intersection over union {iou:.4f}")


def main(folder: Path) -> None:
    trace("numerals", numerals_mask(find(folder, "-7")), "234", "From the reverse version of the owner's logo; the 4's stem is completed under the plus.")
    trace("ask", ask_mask(find(folder, "-2")), "Ask", "From the owner's secondary lockup.")


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser())
