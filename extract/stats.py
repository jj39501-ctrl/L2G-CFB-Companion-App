"""Season stats: OCR every frame of a category and stitch the pages into one table.

Captured as colCC_rowRR.png: row pages overlap by one row, column pages by about
one column, and NAME/POS stay frozen on the left of every column page.
"""

import difflib
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pytesseract
from PIL import Image

from . import fix, table

LAYOUT = table.Layout(header_box=(0.04, 0.225, 0.725, 0.256), body_box=(0.04, 0.28, 0.725, 0.895),
                      name_cols=(0,))
COLS_PER_PAGE = 9                # capture's cols_per_page for season stats
CATEGORIES = ["PASSING", "RUSHING", "RECEIVING", "BLOCKING", "DEFENSE", "KICKING", "PUNTING",
              "KICK RETURN", "PUNT RETURN"]
LABELS = {"scope": (0.07, 0.168, 0.245, 0.212), "category": (0.515, 0.165, 0.70, 0.21)}


def read_label(img: Image.Image, box) -> str:
    """Dark text on a light pill (e.g. 'NATIONAL', 'PASSING')."""
    img = table.normalise(img)
    l, t, r, b = box
    crop = img.crop((int(l * 1920), int(t * 1080), int(r * 1920), int(b * 1080))).convert("L")
    crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    txt = pytesseract.image_to_string(crop, config="--psm 7").strip().upper()
    return re.sub(r"[^A-Z0-9 ()\-]", "", txt).strip()


def read_frame(path: Path):
    """One frame -> (headers, cut flags, rows of cells, flagged cells)."""
    loc, texts, _ = table.read(Image.open(path), LAYOUT)
    rows, flags = [], []
    for ri, cells in enumerate(texts):
        if not any(cells):
            continue
        cells = list(cells)
        cells[0] = fix.player_name(cells[0])
        cells[1] = fix.position(cells[1])
        for ci in range(2, len(cells)):
            if not loc.cut[ci] and not fix.is_number(cells[ci]):
                flags.append({"file": path.name, "row": ri, "column": loc.headers[ci], "read": cells[ci]})
        rows.append(cells)
    return loc.headers, loc.cut, rows, flags


def _key(row):
    return (row[0], row[1])


def _stitch_rows(pages: list[list[list[str]]]) -> list[list[str]]:
    """Join row pages top to bottom, dropping the rows each page repeats from the last."""
    out: list[list[str]] = []
    for page in pages:
        overlap = 0
        for k in range(min(len(out), len(page)), 0, -1):
            if all(_same_row(a, b) for a, b in zip(out[-k:], page[:k])):
                overlap = k
                break
        for i in range(overlap):                       # merge each pair read twice
            a, b = out[len(out) - overlap + i], page[i]
            if not fix.NAME.match(a[0]) and fix.NAME.match(b[0]):
                a[0] = b[0]
            for j in range(min(len(a), len(b))):       # fill cells one frame couldn't place
                if not a[j] and b[j]:
                    a[j] = b[j]
        out.extend(page[overlap:])
    return out


def _same_row(a: list[str], b: list[str]) -> bool:
    """The same table row read in two frames: same player, or (when a name was misread)
    identical stat values across at least three columns."""
    if fix.same_player(_key(a), _key(b)):
        return True
    nums = [(x, y) for x, y in zip(a[2:], b[2:]) if x or y]
    return len(nums) >= 3 and all(x == y for x, y in nums)


def _align(merged: list[dict], rows: list[list[str]]) -> list[int | None]:
    """Index into `merged` for each row of a later column page, matched by player and in
    order, so one misread or missing row can't shift every row after it."""
    out, j = [], 0
    for r in rows:
        hit = next((k for k in range(j, min(j + 4, len(merged)))
                    if fix.same_player((merged[k]["NAME"], merged[k]["POS"]), _key(r))), None)
        out.append(hit)
        if hit is not None:
            j = hit + 1
    # A row read too badly to match, sitting between two rows that did: it's the gap.
    for i in range(1, len(out) - 1):
        if out[i] is None and out[i - 1] is not None and out[i + 1] == out[i - 1] + 2:
            out[i] = out[i - 1] + 1
    return out


def _conform(result, header: list[str]) -> list[list[str]]:
    """A frame's rows laid out like the page's majority header. A frame whose header was
    read with a column more or less (a word split or merged) is mapped column by column
    by name instead of being dropped, which would leave a gap in the stitched rows."""
    heads, _, rows, _ = result
    if len(heads) == len(header):
        return rows
    taken, index = set(), []
    for h in header:
        j = max((j for j in range(len(heads)) if j not in taken),
                key=lambda j: difflib.SequenceMatcher(None, heads[j], h).ratio(), default=None)
        ok = j is not None and difflib.SequenceMatcher(None, heads[j], h).ratio() >= 0.6
        index.append(j if ok else None)
        if ok:
            taken.add(j)
    return [[r[j] if j is not None and j < len(r) else "" for j in index] for r in rows]


def _page_shift(prev: list[str], new: list[str]) -> int:
    """How many stat columns the table scrolled between two column pages, found by
    lining up their headers (capture scrolls 9 at a time; the last page scrolls less).
    Returns len(prev) when nothing overlaps."""
    best, best_score = len(prev), 0.0
    for s in range(1, len(prev)):
        pairs = list(zip(prev[s:], new))
        if not pairs:
            continue
        score = sum(difflib.SequenceMatcher(None, a, b).ratio() for a, b in pairs) / len(pairs)
        score -= abs(s - COLS_PER_PAGE) * 0.001          # tie-break towards the usual scroll
        if score > best_score:
            best, best_score = s, score
    return best if best_score >= 0.5 else len(prev)


def _rename(columns, merged, old, new):
    columns[columns.index(old)] = new
    for row in merged:
        if old in row:
            row[new] = row.pop(old)


def extract_category(folder: Path, pool=None) -> dict:
    files = sorted(folder.glob("col*_row*.png"))
    results = list(pool.map(read_frame, files)) if pool else [read_frame(f) for f in files]
    by_file = dict(zip(files, results))
    cols = sorted({int(f.stem[3:5]) for f in files})

    columns: list[str] = ["NAME", "POS"]
    spellings = Counter(h for res in results for h in res[0])
    prev_heads: list[str] = []
    prev_names: list = []
    merged: list[dict] | None = None
    flags = []
    for c in cols:
        pages = [f for f in files if int(f.stem[3:5]) == c]
        # Headers per column page: most common reading across its row pages.
        heads = [by_file[f][0] for f in pages]
        cuts = [by_file[f][1] for f in pages]
        n = Counter(len(h) for h in heads).most_common(1)[0][0]
        heads_n = [h for h in heads if len(h) == n]
        cut_n = [cu for h, cu in zip(heads, cuts) if len(h) == n]
        header = [Counter(h[i] for h in heads_n).most_common(1)[0][0] for i in range(n)]
        cut = [any(cu[i] for cu in cut_n) for i in range(n)]
        stat = list(range(2, n))
        # On later column pages the first stat column is always half under NAME/POS.
        hidden = [cut[i] or (c != cols[0] and i == 2) for i in stat]
        shift = _page_shift(prev_heads, [header[i] for i in stat])
        rows = _stitch_rows([_conform(by_file[f], header) for f in pages])
        if merged is None:
            merged = [{"NAME": r[0], "POS": r[1]} for r in rows]
            readings = [[(r[0], r[1])] for r in rows]
            targets = list(range(len(rows)))
        else:
            targets = _align(merged, rows)
            missing = sum(t is None for t in targets)
            if missing or len(rows) != len(merged):
                flags.append({"file": f"col{c:02d}", "problem":
                              f"{len(rows)} rows vs {len(merged)}; {missing} couldn't be matched"})
        for r, t in zip(rows, targets):
            if t is not None and c != cols[0]:
                readings[t].append((r[0], r[1]))

        names = []                                      # merged column name per stat column
        for j, i in enumerate(stat):
            prev = prev_names[shift + j] if shift + j < len(prev_names) else None
            if prev:                                    # already taken from the previous page
                names.append(prev)
                if not hidden[j] and spellings[header[i]] > spellings[prev]:
                    _rename(columns, merged, prev, header[i])
                    names[-1] = header[i]
                continue
            if hidden[j] or header[i] in columns:
                names.append(None)
                continue
            columns.append(header[i])
            names.append(header[i])
            for r, t in zip(rows, targets):
                if t is not None:
                    merged[t][header[i]] = fix.to_number(r[i])
            flags.extend(fl for f in pages for fl in by_file[f][3] if fl["column"] == header[i])
        prev_heads, prev_names = [header[i] for i in stat], names

    # Name and position by vote across column pages (each player is under the
    # highlight bar, which reads worst, on at most one of them).
    for row, reads in zip(merged or [], readings if merged else []):
        row["NAME"] = fix.vote([n for n, _ in reads], fix.NAME.match)
        row["POS"] = fix.vote([p for _, p in reads], lambda p: p in fix.POSITIONS)
        if not fix.NAME.match(row["NAME"]):
            flags.append({"problem": "unclear name", "read": [n for n, _ in reads]})

    first = files[0]
    category = read_label(Image.open(first), LABELS["category"])
    return {
        "scope": read_label(Image.open(first), LABELS["scope"]),
        "category": (difflib.get_close_matches(category, CATEGORIES, n=1, cutoff=0.4) or [category])[0],
        "columns": columns,
        "rows": merged or [],
        "flags": flags,
    }


def fill_positions(parts: list[dict]) -> list[dict]:
    """A position no frame could read is filled from the same player in another category."""
    known = {}
    for p in parts:
        for r in p["rows"]:
            if r.get("POS") in fix.POSITIONS:
                known.setdefault(r["NAME"], r["POS"])
    for p in parts:
        for r in p["rows"]:
            if r.get("POS") not in fix.POSITIONS and r["NAME"] in known:
                r["POS"] = known[r["NAME"]]
    return parts
