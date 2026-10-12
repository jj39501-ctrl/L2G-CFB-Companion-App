"""Clean-up rules for OCR'd text: player names, positions, number formats."""

import difflib
import re

POSITIONS = ["QB", "HB", "FB", "WR", "TE", "LT", "LG", "C", "RG", "RT", "LEDG", "REDG", "DT",
             "SAM", "MIKE", "WILL", "CB", "FS", "SS", "K", "P", "ATH"]
# Characters OCR confuses with letters in this font.
AS_LETTER = {"0": "O", "$": "S", "5": "S", "1": "I", "8": "B", "|": "I", "9": "Q"}
NUMBER = re.compile(r"^-?\d{1,3}(,\d{3})*(\.\d+)?%?$|^-?\d+(\.\d+)?%?$")
NAME = re.compile(r"^[A-Z]\.[A-Z][A-Za-z'\-]+( [A-Z][A-Za-z'\-]+)*( (Jr|Sr|II|III|IV)\.?)?$")


def position(t: str) -> str:
    t = "".join(AS_LETTER.get(c, c) for c in t.upper() if not c.isspace())
    if t in POSITIONS:
        return t
    close = difflib.get_close_matches(t, POSITIONS, n=1, cutoff=0.5)
    return close[0] if close else t


def player_name(t: str) -> str:
    """'0.Kromah' -> 'O.Kromah', 'c.Boyd' -> 'C.Boyd', 'L.Jones Ill' -> 'L.Jones III'."""
    t = re.sub(r"[^\x00-\x7f]+", "-", t.strip())                     # Young-Blackgo dash
    t = re.sub(r"^[^A-Za-z0-9$|]+|[^A-Za-z.'\- ]+$", "", t)
    t = re.sub(r"(?<=[a-z])(Jr|Sr|III|II|IV)\.?$", r" \1.", t)          # SarrattJr. -> Sarratt Jr.
    if len(t) >= 2 and t[1] in ".:,;-":
        t = AS_LETTER.get(t[0], t[0]).upper() + "." + t[2:]
    t = re.sub(r"(?<=[A-Za-z'.])0(?=[A-Za-z'1])", "O", t)               # O'Hara read as 0'Hara
    t = re.sub(r"(?<=[A-Za-z])1|1(?=[a-z])", "l", t)                     # Oladokun read as 01adokun
    t = re.sub(r"(?<= )[Il]{2,3}\.?$", lambda m: "I" * len(m.group().rstrip(".")), t)  # III as Ill
    if len(t) > 2 and t[1] == ".":
        t = t[0] + "." + t[2].upper() + t[3:]
    return t.replace(" .", ".").strip()


def merge_name(win: str, tess: str) -> str:
    """Windows OCR reads surnames best but sometimes drops the 'X.' initial; Tesseract
    usually keeps it. Combine the two readings of one cell."""
    win, tess = player_name(win), player_name(tess)
    if NAME.match(win) or not win:
        return win or tess
    if len(tess) > 2 and tess[1] == "." and "." not in win[:3]:
        surname = win[2:] if len(win) > 2 and win[1] in "., " else win
        if re.match(r"^[a-z][A-Z]", surname):
            surname = surname[1:]                                      # 'aBolen': a = misread initial
        guess = tess[0] + "." + surname[:1].upper() + surname[1:]
        if NAME.match(guess):
            return guess
    if NAME.match(tess) and difflib.SequenceMatcher(None, win, tess).ratio() >= 0.5:
        return tess
    return win


def same_player(a: tuple, b: tuple) -> bool:
    """(name, pos) pairs that are the same row read twice, allowing small OCR slips."""
    pos_ok = a[1] == b[1] or a[1] not in POSITIONS or b[1] not in POSITIONS
    return pos_ok and difflib.SequenceMatcher(None, a[0], b[0]).ratio() >= 0.8


def vote(readings: list[str], valid=None) -> str:
    """Most common reading; ties (and junk) broken towards readings that look valid."""
    readings = [r for r in readings if r]
    if not readings:
        return ""
    counts = {r: readings.count(r) for r in readings}
    return max(counts, key=lambda r: (bool(valid and valid(r)), counts[r], len(r)))


def is_number(t: str) -> bool:
    return bool(NUMBER.match(t))


def to_number(t: str):
    """'1,601' -> 1601, '70%' -> 70, '9.1' -> 9.1; anything else unchanged."""
    s = t.replace(",", "").rstrip("%")
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return t
