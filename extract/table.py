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
ROW_H = 26                       # px: height of every row window (matches the glyph templates)
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
    win_text: bool = False       # read other text columns with Windows OCR (Tesseract fills gaps)
    mixed_headers: tuple = ()    # text columns that also hold scores: read cell by cell


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
    # Pure-symbol "words" are the sort arrow misread ("= �"); dropping them stops it
    # bridging two headers into one. "%" stays (it's part of "TD %").
    words = [(d["left"][i] / 2, (d["left"][i] + d["width"][i]) / 2, d["text"][i].strip())
             for i in range(len(d["text"]))
             if any(c.isalnum() or c == "%" for c in d["text"][i])]
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
    mid_bounds = list(bounds)
    # Text columns are left-aligned and can run long ("South Carolina"): let them
    # extend to just before the next header rather than to the midpoint.
    for i in range(len(spans) - 1):
        if i < layout.text_cols or clean_header(spans[i][2]) in layout.text_headers:
            bounds[i + 1] = max(bounds[i + 1], spans[i + 1][0] - 6)
    loc = Located()
    for i, (l, r, t) in enumerate(spans):
        loc.headers.append(clean_header(t))
        loc.cols.append((hx0 + int(bounds[i]), hx0 + int(bounds[i + 1])))
        # Partly hidden: touching the table's right edge, or (past the frozen text
        # columns) flush against the column's left edge, i.e. scrolled under them.
        flush_left = i >= layout.text_cols and l - mid_bounds[i] < CUT_GAP
        loc.cut.append(l < 4 or r > width - 4 or flush_left)

    bx0, by0, bx1, by1 = _px(layout.body_box)
    numeric = [c for i, c in enumerate(loc.cols)
               if i >= layout.text_cols and loc.headers[i] not in layout.text_headers]
    if numeric:          # logos in text columns are taller than text and skew the rows
        bx0, bx1 = max(bx0, numeric[0][0]), min(bx1, numeric[-1][1])
    ink = contrast(np.asarray(img.crop((bx0, by0, bx1, by1)).convert("L"))) > INK
    on = ink.sum(axis=1) > 2
    start = None
    for y, v in enumerate(list(on) + [False]):
        if v and start is None:
            start = y
        elif not v and start is not None:
            if y - start >= ROW_MIN:
                # Fixed-height window centred on the line: icons (rank arrows, logos)
                # stretch some bands, which would misplace digits against the templates.
                cy = by0 + (start + y) // 2
                loc.rows.append((cy - ROW_H // 2, cy + ROW_H // 2))
            start = None
    return loc


def clean_header(t: str) -> str:
    """Drop the sort arrow (read as junk or a lone 'V') and stray punctuation."""
    t = " ".join(t.upper().split())
    t = re.sub(r"^(?:[^A-Z0-9\[]+|V |W |[\[|] ?)+", "", t)
    t = re.sub(r"(?<=FG[MA])(?:SO|S0|5O)", "50", t)                    # FGM50 read as FGMSO
    t = re.sub(r"^[^A-Z ]{1,2} (?=[A-Z]{3})|^[A-Z0-9] (?=[A-Z]{3,})", "", t)  # sort arrow read as '4 DATE' 
    return t.strip(" *-:;'\"‘’|[")


def read_column_win(img: Image.Image, x0: int, x1: int, rows: list, inset: int = 0) -> list[str]:
    """A text column via Windows OCR (much better than Tesseract on this font's words,
    though it skips very short items). One call for the whole column at 2x; words are
    assigned to rows by y."""
    from . import winocr
    y0, y1 = rows[0][0], rows[-1][1]
    crop = img.crop((x0 + inset, y0, x1, y1)).convert("L")
    a = np.asarray(crop).astype(np.int16).copy()
    light = np.median(a, axis=1) > 128           # the highlight bar: make it light-on-dark too
    a[light] = 255 - a[light]
    crop = Image.fromarray(a.astype(np.uint8)).convert("RGB")
    crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    out = [""] * len(rows)
    for line in winocr.lines(crop):
        for w in line["words"]:
            cy = y0 + (w["y"] + w["h"] / 2) / 2
            ri = next((i for i, (a, b) in enumerate(rows) if a <= cy <= b), None)
            if ri is not None:
                out[ri] = (out[ri] + " " + w["text"]).strip()
    return out


def _content(t: str) -> int:
    """How much real content a reading has: letters and digits, minus OCR junk."""
    return sum(c.isalnum() for c in t) - 3 * sum(c in "|[]{}~`_=\\<>" for c in t)


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
        win = None
        if ci in layout.name_cols:
            win = read_column_win(img, x0, x1, loc.rows, inset=12)   # skip the highlight's gold edge
        elif as_text and layout.win_text:
            win = read_column_win(img, x0, x1, loc.rows)
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
                    texts[ri][ci] = fix.merge_name(win[ri], texts[ri][ci])
            elif win is not None and loc.headers[ci] not in layout.mixed_headers:
                for ri in range(len(loc.rows)):          # words (teams): Windows, Tesseract fills gaps
                    texts[ri][ci] = fix.text(win[ri] or texts[ri][ci])
            elif win is not None:
                # Mixed text+score cells ("W 34-7 vs 10 Alabama"): Tesseract one cell at a
                # time beats both column reads, Windows drops scores. Keep the fuller one.
                for ri, (y0, y1) in enumerate(loc.rows):
                    cell = pytesseract.image_to_string(_ink_image(gray.crop((x0, y0, x1, y1)), 3),
                                                       config="--psm 7").strip()
                    texts[ri][ci] = fix.text(max([cell, win[ri], texts[ri][ci]], key=_content))
        else:
            win = read_column_win(img, x0, x1, loc.rows)        # second opinion, see pick_number
            for ri, (y0, y1) in enumerate(loc.rows):
                ink = contrast(np.asarray(gray.crop((x0, y0, x1, y1))))
                # Re-centre the window on this cell's own digits so they line up with
                # the templates however the row band was skewed.
                rows_on = np.nonzero((ink > 0.35).sum(axis=1) >= 1)[0]
                if rows_on.size:
                    cy = y0 + (rows_on[0] + rows_on[-1]) // 2
                    ink = contrast(np.asarray(gray.crop((x0, cy - ROW_H // 2, x1, cy + ROW_H // 2))))
                texts[ri][ci], confs[ri][ci] = _reader.read(ink)
                texts[ri][ci] = fix.pick_number(texts[ri][ci], win[ri])
    return loc, texts, confs
