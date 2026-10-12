"""Read one captured table frame into rows of cells.

Columns come from the header row: Tesseract reads the header words, words close
together merge into one header ("TD %"), and column boundaries sit midway between
neighbouring headers. Rows come from the horizontal ink profile of the body.
Text columns (names, positions, teams) go to Tesseract; numeric columns go to the
glyph matcher.
"""

import re
from dataclasses import dataclass, field

import numpy as np
import pytesseract
from PIL import Image

from . import fix
from .glyphs import GlyphReader, contrast

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

STD = (1920, 1080)               # every frame is normalised to this before reading
CUT_GAP = 8                      # px: a header this close to its column's left edge is cut off
HEADER_GAP = 18                  # px: header words closer than this are one header
ROW_MIN = 14                     # px: shortest text line that counts as a table row
INK = 0.25                       # ink level (0..1 of the line's contrast) that counts as text


@dataclass
class Layout:
    """Where a table sits, as picture fractions."""
    header_box: tuple            # the column-header row
    body_box: tuple              # the data rows
    text_cols: int = 2           # leading columns read as text (NAME, POS)
    text_headers: tuple = ()     # other headers to read as text wherever they appear
    name_cols: tuple = ()        # columns holding "X.Lastname" player names (read specially)


@dataclass
class Located:
    headers: list = field(default_factory=list)   # header names
    cols: list = field(default_factory=list)      # (x0, x1) absolute px per column
    rows: list = field(default_factory=list)      # (y0, y1) absolute px per row
    cut: list = field(default_factory=list)       # column touches the table edge (partly hidden)


STATS_LAYOUT = Layout(header_box=(0.04, 0.225, 0.725, 0.256), body_box=(0.04, 0.28, 0.725, 0.895))


def normalise(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    return img if img.size == STD else img.resize(STD, Image.LANCZOS)


def _px(box):
    l, t, r, b = box
    return int(l * STD[0]), int(t * STD[1]), int(r * STD[0]), int(b * STD[1])


def _ink_image(gray: Image.Image, scale: int = 2) -> Image.Image:
    """Dark text on white, upscaled, for Tesseract."""
    g = gray.resize((gray.width * scale, gray.height * scale), Image.LANCZOS)
    d = contrast(np.asarray(g))
    return Image.fromarray((255 - np.clip(d * 1.5, 0, 1) * 255).astype(np.uint8))


def locate(img: Image.Image, layout: Layout) -> Located:
    hx0, hy0, hx1, hy1 = _px(layout.header_box)
    head = _ink_image(img.crop((hx0, hy0, hx1, hy1)).convert("L"))
    d = pytesseract.image_to_data(head, config="--psm 7", output_type=pytesseract.Output.DICT)
    words = [(d["left"][i] / 2, (d["left"][i] + d["width"][i]) / 2, d["text"][i].strip())
             for i in range(len(d["text"])) if d["text"][i].strip()]
    spans = []
    for l, r, t in words:
        # Merge close words ("TD %"), but never into the frozen text columns: a
        # half-hidden column often sits right against POS.
        if spans and len(spans) > layout.text_cols and l - spans[-1][1] < HEADER_GAP:
            spans[-1] = (spans[-1][0], r, spans[-1][2] + " " + t)
        else:
            spans.append((l, r, t))
    width = hx1 - hx0
    bounds = [0] + [(spans[i][1] + spans[i + 1][0]) / 2 for i in range(len(spans) - 1)] + [width]
    loc = Located()
    for i, (l, r, t) in enumerate(spans):
        loc.headers.append(clean_header(t))
        loc.cols.append((hx0 + int(bounds[i]), hx0 + int(bounds[i + 1])))
        # Partly hidden: touching the table's right edge, or (past the frozen text
        # columns) flush against the column's left edge, i.e. scrolled under them.
        flush_left = i >= layout.text_cols and l - bounds[i] < CUT_GAP
        loc.cut.append(l < 4 or r > width - 4 or flush_left)

    bx0, by0, bx1, by1 = _px(layout.body_box)
    ink = contrast(np.asarray(img.crop((bx0, by0, bx1, by1)).convert("L"))) > INK
    on = ink.sum(axis=1) > 2
    start = None
    for y, v in enumerate(list(on) + [False]):
        if v and start is None:
            start = y
        elif not v and start is not None:
            if y - start >= ROW_MIN:
                loc.rows.append((by0 + start - 3, by0 + y + 3))
            start = None
    return loc


def clean_header(t: str) -> str:
    """Drop the sort arrow (read as junk or a lone 'V') and stray punctuation."""
    t = " ".join(t.upper().split())
    t = re.sub(r"^(?:[^A-Z0-9\[]+|V |W |[\[|] ?)+", "", t)
    t = re.sub(r"(?<=FG[MA])(?:SO|S0|5O)", "50", t)                    # FGM50 read as FGMSO
    return t.strip(" *-:;'\"‘’|[")


def read_names(img: Image.Image, x0: int, x1: int, rows: list) -> list[str]:
    """Player names via Windows OCR (Tesseract garbles 'X.' initials in this font).
    One call for the whole column at 2x; words are assigned to rows by y."""
    from . import winocr
    y0, y1 = rows[0][0], rows[-1][1]
    crop = img.crop((x0 + 12, y0, x1, y1))      # +12: skip the highlight bar's gold edge
    crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    out = [""] * len(rows)
    for line in winocr.lines(crop):
        for w in line["words"]:
            cy = y0 + (w["y"] + w["h"] / 2) / 2
            ri = next((i for i, (a, b) in enumerate(rows) if a <= cy <= b), None)
            if ri is not None:
                out[ri] = (out[ri] + " " + w["text"]).strip()
    return out


_reader = None


def read(img: Image.Image, layout: Layout) -> tuple[Located, list[list[str]], list[list[float]]]:
    """Returns (located, cell texts, cell confidences)."""
    global _reader
    _reader = _reader or GlyphReader()
    img = normalise(img)
    loc = locate(img, layout)
    gray = img.convert("L")
    texts = [[""] * len(loc.cols) for _ in loc.rows]
    confs = [[1.0] * len(loc.cols) for _ in loc.rows]
    for ci, (x0, x1) in enumerate(loc.cols):
        as_text = ci < layout.text_cols or loc.headers[ci] in layout.text_headers
        if ci in layout.name_cols:
            names = read_names(img, x0, x1, loc.rows)
        if ci in layout.name_cols or as_text:
            # one Tesseract call per column strip; words are assigned to rows by y
            y0, y1 = loc.rows[0][0], loc.rows[-1][1]
            strip = _ink_image(gray.crop((x0, y0, x1, y1)))
            d = pytesseract.image_to_data(strip, config="--psm 6", output_type=pytesseract.Output.DICT)
            for i, t in enumerate(d["text"]):
                if not t.strip():
                    continue
                yc = y0 + (d["top"][i] + d["height"][i] / 2) / 2
                for ri, (ry0, ry1) in enumerate(loc.rows):
                    if ry0 <= yc <= ry1:
                        texts[ri][ci] = (texts[ri][ci] + " " + t.strip()).strip()
                        confs[ri][ci] = min(confs[ri][ci], float(d["conf"][i]) / 100)
                        break
            if ci in layout.name_cols:
                for ri in range(len(loc.rows)):
                    texts[ri][ci] = fix.merge_name(names[ri], texts[ri][ci])
        else:
            for ri, (y0, y1) in enumerate(loc.rows):
                ink = contrast(np.asarray(gray.crop((x0, y0, x1, y1))))
                texts[ri][ci], confs[ri][ci] = _reader.read(ink)
    return loc, texts, confs
