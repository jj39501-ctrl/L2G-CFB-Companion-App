"""Read numbers by matching the game's own digit shapes.

Tesseract's general model misreads the game's condensed font (7 vs 1, dropped
decimal points). The game draws every number in the same font at the same size,
so we slide reference glyphs (cut from frames with known values, see
templates/) along each cell and keep the best non-overlapping matches.

Frames are normalised to a 1080-line picture first, so templates hold for any
capture resolution.
"""

from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image
from scipy import ndimage

TEMPLATES = Path(__file__).resolve().parent / "templates"
MATCH_MIN = 0.55                 # weakest correlation accepted as a character
MAX_OVERLAP = 0.3                # accepted matches may overlap this much of the narrower one
V_SHIFT = 2                      # pixels of vertical slack when matching (rows differ by 1-2px)
PER_CHAR = 2                     # templates used per character (speed vs robustness)
DOT_MAX_H = 0.4                  # a dot is shorter than this fraction of the digit height

# File names can't hold some characters.
SAFE = {".": "dot", "%": "pct", "-": "minus", ":": "colon", "/": "slash", "+": "plus"}
UNSAFE = {v: k for k, v in SAFE.items()}


def contrast(gray: np.ndarray) -> np.ndarray:
    """Ink map 0..1: distance from each pixel line's median (the row background), so
    light-on-dark rows and the dark-on-light highlight row look the same."""
    a = gray.astype(np.float32)
    d = np.abs(a - np.median(a, axis=1, keepdims=True))
    m = d.max()
    return d / m if m > 0 else d


def _zncc_scan(cell: np.ndarray, tpl: np.ndarray) -> np.ndarray:
    """Best zero-mean normalised correlation of tpl at each x (over small y shifts)."""
    th, tw = tpl.shape
    ch, cw = cell.shape
    if cw < tw:
        return np.full(0, -1.0)
    pad = max(th + 2 * V_SHIFT - ch, 0)
    if pad:
        cell = np.pad(cell, ((pad // 2 + 1, pad - pad // 2 + 1), (0, 0)))
    t = tpl - tpl.mean()
    tn = np.sqrt((t * t).sum()) or 1.0
    best = np.full(cell.shape[1] - tw + 1, -1.0)
    cy = (cell.shape[0] - th) // 2
    for dy in range(-V_SHIFT, V_SHIFT + 1):
        y = cy + dy
        if y < 0 or y + th > cell.shape[0]:
            continue
        win = sliding_window_view(cell[y:y + th], (th, tw))[0]          # (n, th, tw)
        w = win - win.mean(axis=(1, 2), keepdims=True)
        wn = np.sqrt((w * w).sum(axis=(1, 2)))
        score = (w * t).sum(axis=(1, 2)) / (wn * tn + 1e-6)
        best = np.maximum(best, score)
    return best


class GlyphReader:
    def __init__(self, folder: Path = TEMPLATES):
        self.templates: list[tuple[str, np.ndarray]] = []
        for p in sorted(folder.glob("*.png")):
            name, n = p.stem.rsplit("_", 1)
            char = UNSAFE.get(name, name)
            if char == "." or int(n) >= PER_CHAR:          # dots are found structurally
                continue
            self.templates.append((char, np.asarray(Image.open(p).convert("L"), np.float32) / 255))

    def read(self, cell: np.ndarray) -> tuple[str, float]:
        """Read a cell's ink map. Returns (text, margin): how far the weakest character
        beat the best different character at its position (small = ambiguous)."""
        if cell.max() < 0.3:
            return "", 1.0                                             # empty cell
        cands = []
        for char, tpl in self.templates:
            scores = _zncc_scan(cell, tpl)
            tw = tpl.shape[1]
            # local maxima above threshold
            for x in np.nonzero(scores >= MATCH_MIN)[0]:
                lo, hi = max(x - tw // 3, 0), x + tw // 3 + 1
                if scores[x] >= scores[lo:hi].max():
                    cands.append((float(scores[x]), int(x), tw, char))
        cands.sort(reverse=True)
        taken = []
        for score, x, tw, char in cands:
            if cell[:, x:x + tw].max() < 0.5:
                continue                                   # correlation on background noise
            if all(min(x + tw, x2 + w2) - max(x, x2) <= MAX_OVERLAP * min(tw, w2)
                   for _, x2, w2, _ in taken):
                taken.append((score, x, tw, char))
        if not taken:
            return "", 0.0
        margin = 1.0
        for score, x, tw, char in taken:
            rivals = [sc for sc, x2, w2, c2 in cands
                      if c2 != char and abs((x2 + w2 / 2) - (x + tw / 2)) < 0.4 * tw]
            if rivals:
                margin = min(margin, score - max(rivals))
        chars = [(x + tw / 2, char) for _, x, tw, char in taken] + _marks(cell)
        text = "".join(c for _, c in sorted(chars))
        return text, margin


def _marks(cell: np.ndarray) -> list[tuple[float, str]]:
    """Small punctuation found by shape rather than templates: decimal points (small blob
    on the baseline), commas (dipping below it) and minus signs (short wide bar at mid
    height). Returns (x centre, char)."""
    lab, _ = ndimage.label(cell > 0.35)
    boxes = [(s[0].start, s[0].stop, s[1].start, s[1].stop) for s in ndimage.find_objects(lab)]
    if not boxes:
        return []
    tall = max(y1 - y0 for y0, y1, _, _ in boxes)
    digits = [b for b in boxes if b[1] - b[0] > 0.7 * tall]
    base = max(y1 for _, y1, _, _ in digits)
    top = min(y0 for y0, _, _, _ in digits)
    out = []
    for y0, y1, x0, x1 in boxes:
        h, w = y1 - y0, x1 - x0
        if h >= DOT_MAX_H * tall or h * w < 4:
            continue
        mid = (y0 + y1) / 2
        if w > 1.3 * h and top + 0.25 * tall < mid < base - 0.25 * tall:
            out.append(((x0 + x1) / 2, "-"))
        elif y1 > base + 1 and w < 0.5 * tall:
            out.append(((x0 + x1) / 2, ","))
        elif abs(y1 - base) <= 3 and w < 0.5 * tall:
            out.append(((x0 + x1) / 2, "."))
    return out


def save_template(char: str, ink: np.ndarray, folder: Path = TEMPLATES):
    folder.mkdir(exist_ok=True)
    name = SAFE.get(char, char)
    n = len(list(folder.glob(f"{name}_*.png")))
    Image.fromarray((np.clip(ink, 0, 1) * 255).astype(np.uint8)).save(folder / f"{name}_{n}.png")
