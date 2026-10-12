"""Cut digit/punctuation templates from a hand-checked frame (tools/truth/*.png + .txt).

Each .txt line is one table row: two text columns (NAME POS) then the numeric
columns, matching the table layout given below. Only cells whose connected
components split cleanly into the expected number of characters are used.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract import table  # noqa: E402
from extract.glyphs import TEMPLATES, contrast, save_template  # noqa: E402

PER_CHAR = 4                     # examples kept per character


def components(ink: np.ndarray):
    m = ink > 0.35
    lab, _ = ndimage.label(m)
    comps = sorted([s[1].start, s[1].stop, s[0].start, s[0].stop]
                   for s in ndimage.find_objects(lab) if s is not None)
    comps = [c for c in comps if (c[1] - c[0]) * (c[3] - c[2]) >= 4]
    if not comps:
        return []
    hmax = max(c[3] - c[2] for c in comps)
    out = []
    for c in comps:
        small = (c[3] - c[2]) < 0.45 * hmax
        if (out and not small and not out[-1][4]
                and min(out[-1][1], c[1]) - max(out[-1][0], c[0]) > 0.5 * min(c[1] - c[0], out[-1][1] - out[-1][0])):
            o = out[-1]
            out[-1] = [min(o[0], c[0]), max(o[1], c[1]), 0, 0, False]
        else:
            out.append(c + [small])
    return out


def main():
    for old in TEMPLATES.glob("*.png"):
        old.unlink()
    counts: dict[str, int] = {}
    for png in sorted((Path(__file__).parent / "truth").glob("*.png")):
        rows = [l.split() for l in png.with_suffix(".txt").read_text().splitlines()
                if l.strip() and not l.startswith("#")]
        img = table.normalise(Image.open(png))
        layout = table.locate(img, table.STATS_LAYOUT)
        for ri, (y0, y1) in enumerate(layout.rows):
            if ri == 0:
                continue                                   # skip the highlight row: blurrier
            for ci in range(2, len(layout.cols)):
                x0, x1 = layout.cols[ci]
                ink = contrast(np.asarray(img.crop((x0, y0, x1, y1)).convert("L")))
                want = rows[ri][ci]
                parts = components(ink)
                if len(parts) != len(want):
                    continue
                for (gx0, gx1, *_), ch in zip(parts, want):
                    if counts.get(ch, 0) < PER_CHAR:
                        save_template(ch, ink[:, max(gx0 - 1, 0):gx1 + 1])
                        counts[ch] = counts.get(ch, 0) + 1
    print("templates:", dict(sorted(counts.items())))


if __name__ == "__main__":
    main()
