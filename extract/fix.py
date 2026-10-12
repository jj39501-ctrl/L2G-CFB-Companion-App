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


UPPER = {"Fcs": "FCS", "Usc": "USC", "Lsu": "LSU", "Ucf": "UCF", "Tcu": "TCU", "Smu": "SMU",
         "Uab": "UAB", "Byu": "BYU", "Unlv": "UNLV", "Utep": "UTEP", "Utsa": "UTSA", "Fiu": "FIU",
         "Fau": "FAU", "Ul": "UL", "Ncs": "NCS"}


def text(t: str) -> str:
    """General clean-up for team/opponent text."""
    t = " ".join(t.split())
    t = re.sub(r"\bA[S5$G&]M\b", "A&M", t)                           # Texas A&M read as ASM
    t = re.sub(r"\b[A-Za-z]+\b", lambda m: UPPER.get(m.group().capitalize(), m.group()), t)
    t = re.sub(r"^w(?= \d)", "W", t)
    t = re.sub(r"\bl(?=[a-z]{2})", "I", t)                           # lowa -> Iowa
    return t.strip(" |[]{}~`_=")


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


_TEAMS = None


def teams() -> list[str]:
    global _TEAMS
    if _TEAMS is None:
        from pathlib import Path
        lines = (Path(__file__).parent / "teams.txt").read_text(encoding="utf-8").splitlines()
        _TEAMS = [l.split("=")[0].strip() for l in lines if l.strip() and not l.startswith("#")]
        for l in lines:                                # "UAB = IJAB, YAB": known misreads
            if "=" in l and not l.startswith("#"):
                name, alts = l.split("=", 1)
                ALIASES.update({a.strip().lower(): name.strip() for a in alts.split(",")})
    return _TEAMS


ALIASES: dict[str, str] = {}


def _unalias(t: str) -> str:
    teams()
    return re.sub(r"[A-Za-z]+", lambda m: ALIASES.get(m.group().lower(), m.group()), t)


def find_teams(t: str) -> list[tuple[int | None, str]]:
    """Every known team named in a line, left to right, with the rank before each."""
    t = _unalias(text(t))
    low = t.lower()
    hits = []
    for n in sorted(teams(), key=len, reverse=True):
        i = low.find(n.lower())
        if i >= 0 and len(n) >= 3 and not any(a <= i < b for a, b, _ in hits):
            hits.append((i, i + len(n), n))
    out = []
    for i, _, n in sorted(hits):
        m = re.search(r"(\d{1,2})\D{0,2}$", t[:i])
        out.append((int(m.group(1)) if m and 1 <= int(m.group(1)) <= 25 else None, n))
    return out


def team(t: str) -> tuple[int | None, str, bool]:
    """'Q) 19 Oklahoma' -> (19, 'Oklahoma', True). Matches the longest run of trailing words
    against teams.txt; a number just before it is the team's ranking. The bool says
    whether the team was recognised (if not, the cleaned text is returned)."""
    t = _unalias(re.sub(r"\s*\(\d+\)\s*$", "", text(t)))              # poll votes "(41)"
    t = re.sub(r"\[OH\]", "(OH)", t)
    words = t.split()
    lower = {n.lower(): n for n in teams()}
    best = None
    for k in range(min(4, len(words)), 0, -1):
        if any(re.match(r"^\W*\d", w) for w in words[-k:]):
            continue                                   # holds a ranking number: not part of the name
        cand = " ".join(words[-k:])
        hit = difflib.get_close_matches(cand.lower(), lower, n=1, cutoff=0.8)
        if hit:
            best = (k, lower[hit[0]])
            break
    if best is None:
        # Logo debris glued to a word ("5sLSU"): look for a known name inside the text.
        low = t.lower()
        inside = [n for n in teams() if len(n) >= 3 and n.lower() in low]
        if inside:
            name = max(inside, key=lambda n: (low.rfind(n.lower()) + len(n), len(n)))
            m = re.search(r"(\d{1,2})\D{0,2}$", t[:low.rfind(name.lower())])
            rank = int(m.group(1)) if m and 1 <= int(m.group(1)) <= 25 else None
            return rank, name, True
        m = re.search(r"(?:(\d{1,2})\s+)?([A-Z][A-Za-z&.'()]*(?:\s+[A-Z(][A-Za-z&.'()]*)*)\s*$", text(t))
        return (int(m.group(1)) if m and m.group(1) else None, m.group(2) if m else text(t), False)
    k, name = best
    rank = None
    if len(words) > k:
        m = re.search(r"(\d{1,2})\W*$", words[-k - 1])             # 's13' -> 13, '(3' -> 3
        if m and 1 <= int(m.group(1)) <= 25:
            rank = int(m.group(1))
    return rank, name, True


def pick_number(glyph: str, win: str) -> str:
    """Two readings of a number cell. Template matching (glyph) reads every cell but can
    confuse 6/8; Windows OCR skips short numbers and sometimes doubles a digit, but when
    it returns the same length (or the same digits plus a '-' or ',' the templates
    missed) it's right."""
    win = win.replace(" ", "")
    if not win or not is_number(win.replace("-", "", 1) if "-" in win[1:] else win):
        return glyph
    digits = lambda t: re.sub(r"\D", "", t)
    if len(win) == len(glyph) or digits(win) == digits(glyph):
        return win
    return glyph


def rank(t: str) -> int | None:
    """Ranking cell, with the up/down arrow often read as a trailing '-' or '1'."""
    d = re.sub(r"\D", "", t)
    for n in (2, 1):
        if d[:n] and 1 <= int(d[:n]) <= 25 and (n == 1 or len(d) >= 2):
            return int(d[:n])
    return None


def members() -> list[str]:
    from pathlib import Path
    p = Path(__file__).parent / "members.txt"
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def member(t: str, known: list[str]) -> str:
    """Snap an OCR'd gamertag to the league's list (members.txt), allowing small slips."""
    t = t.strip()
    hit = difflib.get_close_matches(t.lower(), [k.lower() for k in known], n=1, cutoff=0.7)
    return next(k for k in known if k.lower() == hit[0]) if hit else t
