"""Extractors for the table screens other than season stats.

Each takes the screen's capture folder (and a process pool) and returns a list of
parts (one per conference/scope where the screen has a drop-down), each a dict with
the parsed rows and a "flags" list for review.json.
"""

import difflib
import re
from pathlib import Path

import pytesseract
from PIL import Image

from . import fix, table, winocr

BODY = (0.04, 0.278, 0.725, 0.899)
HEADER = (0.04, 0.236, 0.725, 0.264)
LEFT_LABEL = (0.07, 0.168, 0.26, 0.218)       # the L2 pill: conference / week / poll
RIGHT_LABEL = (0.515, 0.165, 0.70, 0.215)     # the R2 pill: scope

TOP25 = table.Layout(HEADER, BODY, text_cols=0, win_text=True,
                     text_headers=("NAME/VOTES", "LAST WEEK", "THIS WEEK"),
                     mixed_headers=("LAST WEEK", "THIS WEEK"))
STANDINGS = table.Layout(HEADER, BODY, text_cols=1, win_text=True)
SCHEDULE = table.Layout(HEADER, BODY, text_cols=1, win_text=True,
                        text_headers=("DATE", "TIME(ET)/RESULT", "TV"),
                        mixed_headers=("MATCHUP", "TIME(ET)/RESULT"))
HEISMAN = table.Layout((0.05, 0.308, 0.725, 0.336), (0.05, 0.35, 0.725, 0.75), text_cols=0,
                       win_text=True, text_headers=("POS", "NAME", "TEAM", "YEAR", "CHANGE"))

CONFERENCES = ["ACC", "American", "Big 12", "Big Ten", "CUSA", "Independent", "MAC", "MW",
               "Pac-12", "SEC", "Sun Belt", "Sun Belt (East)", "Sun Belt (West)", "National"]


def label(path: Path, box) -> str:
    """Text of a header pill (dark on light): cropped inside the pill's border and slanted
    end, enlarged and padded with white, which Windows OCR reads reliably."""
    img = table.normalise(Image.open(path))
    l, t, r, b = box
    # Left pills are slanted (and empty) at the right end; right pills at the left end.
    trim_l, trim_r = (6, 30) if box == LEFT_LABEL else (30, 6)
    crop = img.crop((int(l * 1920) + trim_l, int(t * 1080) + 6, int(r * 1920) - trim_r, int(b * 1080) - 6))
    crop = crop.convert("L").resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
    pad = Image.new("L", (crop.width + 80, crop.height + 80), 255)
    pad.paste(crop, (40, 40))
    return winocr.text(pad.convert("RGB")).strip()


def snap(text: str, options: list[str]) -> str:
    hit = difflib.get_close_matches(text.lower(), [o.lower() for o in options], n=1, cutoff=0.5)
    return next(o for o in options if o.lower() == hit[0]) if hit else text


def _read(path: Path, layout):
    loc, texts, _ = table.read(Image.open(path), layout)
    return loc.headers, [r for r in texts if any(r)]


def _frames(folder: Path, layout, pool):
    files = sorted(folder.glob("col*_row*.png")) or sorted(folder.glob("frame.png"))
    results = list(pool.map(_read, files, [layout] * len(files))) if pool else [_read(f, layout) for f in files]
    return files, results


def _stitch(results, key) -> tuple[list[str], list[dict]]:
    """Frames -> one list of row dicts (by header), dropping rows already seen (by key)."""
    headers = max((h for h, _ in results), key=len) if results else []
    rows, seen = [], set()
    for heads, frame_rows in results:
        for r in frame_rows:
            row = dict(zip(heads, r))
            k = key(row)
            if k and k not in seen:
                seen.add(k)
                rows.append(row)
    return headers, rows


def _num(t: str):
    t = (t or "").strip()
    return fix.to_number(t) if fix.is_number(t) else (t or None)


def top25(folder: Path, pool=None) -> list[dict]:
    files, results = _frames(folder, TOP25, pool)
    _, rows = _stitch(results, key=lambda r: fix.team(r.get("NAME/VOTES", ""))[1])
    out, flags = [], []
    for r in rows:
        rank, team, known = fix.team(r.get("NAME/VOTES", ""))
        votes = re.search(r"\((\d+)\)", r.get("NAME/VOTES", ""))
        if not known:
            flags.append({"problem": "unknown team", "read": r.get("NAME/VOTES")})
        out.append({
            "rank": fix.rank(r.get("RANK", "")),
            # "NR" (unranked) comes out of the digit reader as junk like "119"
            "last_week": int(re.sub(r"\D", "", r.get("LW", "")) or 99)
                         if 1 <= int(re.sub(r"\D", "", r.get("LW", "")) or 99) <= 25 else "NR",
            "team": team,
            "first_place_votes": int(votes.group(1)) if votes else 0,
            "record": re.sub(r"^(\d)(\d)$", r"\1-\2", r.get("W-L", "")),
            "points": _num(r.get("PTS")),
            "last_game": r.get("LAST WEEK") or None,
            "next_game": r.get("THIS WEEK") or None,
        })
    out.sort(key=lambda r: r["rank"] if isinstance(r["rank"], int) else 99)
    if len(out) != 25:
        flags.append({"problem": f"{len(out)} teams, expected 25"})
    return [{"poll": label(files[0], LEFT_LABEL).title(), "rows": out, "flags": flags}]


def standings(folder: Path, pool=None) -> list[dict]:
    parts = []
    for conf in sorted(folder.glob("conference*")):
        files, results = _frames(conf, STANDINGS, pool)
        headers, rows = _stitch(results, key=lambda r: fix.team(r.get("TEAM", ""))[1])
        out, flags = [], []
        for r in rows:
            rank, team, known = fix.team(r.get("TEAM", ""))
            if not known:
                flags.append({"problem": "unknown team", "read": r.get("TEAM")})
            row = {"team": team, "rank": rank}
            for h in headers[1:]:
                row[h.lower().replace(" ", "_")] = _num(r.get(h))
            out.append(row)
        parts.append({"conference": snap(label(files[0], LEFT_LABEL), CONFERENCES[:-1]),
                      "rows": out, "flags": flags})
    fill_in_order(parts, "conference", CONFERENCES[:-1])
    return parts


def fill_in_order(parts: list[dict], key: str, order: list[str]):
    """The capture steps through the drop-down one entry at a time, in its order, starting
    wherever it was left. Line the read labels up against that order (best offset) and
    take every label from it, so one misread ('Big 12' twice) can't mislabel a part."""
    n = len(order)
    if not parts:
        return
    offset = max(range(n), key=lambda k: sum(p[key] == order[(k + i) % n] for i, p in enumerate(parts)))
    for i, p in enumerate(parts):
        want = order[(offset + i) % n]
        if p[key] != want:
            p["flags"].append({"problem": f"{key} label read as {p[key]!r}; set to {want!r} from drop-down order"})
            p[key] = want


def schedule(folder: Path, pool=None) -> list[dict]:
    files, results = _frames(folder, SCHEDULE, pool)
    _, rows = _stitch(results, key=lambda r: r.get("MATCHUP", ""))
    games, flags = [], []
    for r in rows:
        parts = re.split(r"\s+(at|vs\.?)\s+", r.get("MATCHUP", ""), maxsplit=1)
        if len(parts) != 3:
            # "at" lost to a logo: fall back to the two known teams found in the text
            found = fix.find_teams(r.get("MATCHUP", ""))
            if len(found) != 2:
                flags.append({"problem": "unreadable matchup", "read": r.get("MATCHUP")})
                continue
            (away_rank, away), (home_rank, home) = found
            parts, ok1, ok2 = ["", "at", ""], True, True
        else:
            away_rank, away, ok1 = fix.team(parts[0])
            home_rank, home, ok2 = fix.team(parts[2])
        if not (ok1 and ok2):
            flags.append({"problem": "unknown team", "read": r.get("MATCHUP")})
        result = r.get("TIME(ET)/RESULT", "")
        score = re.match(r"^([A-Z&]+)\s+(\d+),\s*([A-Z&]+)\s+(\d+)$", result.replace(".", ","))
        games.append({
            "away": away, "away_rank": away_rank, "home": home, "home_rank": home_rank,
            "neutral": parts[1].startswith("vs"),
            "date": fix.text(r.get("DATE", "")).title() or None,
            "time": None if score else (result or None),
            "final": {"winner": score.group(1), "winner_score": int(score.group(2)),
                      "loser": score.group(3), "loser_score": int(score.group(4))} if score else None,
        })
    week = label(files[0], LEFT_LABEL)
    return [{"week": week.title(), "scope": label(files[0], RIGHT_LABEL).title(),
             "games": games, "flags": flags}]


def heisman_watch(folder: Path, pool=None) -> list[dict]:
    files, results = _frames(folder, HEISMAN, pool)
    _, rows = _stitch(results, key=lambda r: r.get("NAME", ""))
    out, flags = [], []
    for i, r in enumerate(rows, 1):
        rank, team, known = fix.team(r.get("TEAM", ""))
        if not known:
            flags.append({"problem": "unknown team", "read": r.get("TEAM")})
        out.append({"place": i, "name": fix.text(r.get("NAME", "")), "pos": fix.position(r.get("POS", "")),
                    "team": team, "team_rank": rank, "year": r.get("YEAR") or None,
                    "change": r.get("CHANGE") or None})
    return [{"rows": out, "flags": flags}]


POTW_WEEK = (0.745, 0.18, 0.93, 0.222)        # "SEASON WEEK 1" pill, top right
CARDS = {"defensive": (0.36, 0.245, 0.96, 0.545), "offensive": (0.36, 0.555, 0.96, 0.86)}


def _box(img: Image.Image, box, scale=2) -> list[dict]:
    l, t, r, b = box
    crop = img.crop((int(l * 1920), int(t * 1080), int(r * 1920), int(b * 1080)))
    lines = winocr.lines(crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS))
    for ln in lines:
        ln["x"], ln["y"] = ln["words"][0]["x"] / scale, ln["words"][0]["y"] / scale
    return sorted(lines, key=lambda ln: ln["y"])


def _card(img: Image.Image, box) -> dict:
    lines = [ln for ln in _box(img, box) if ln["x"] < 0.6 * (box[2] - box[0]) * 1920]
    l, t, r, b = box
    # "CB | #7" in the card's top-right corner: Windows OCR skips it, Tesseract reads it.
    tag_crop = img.crop((int(0.84 * 1920), int((t + 0.02) * 1080), int(0.93 * 1920), int((t + 0.10) * 1080)))
    tag = pytesseract.image_to_string(table._ink_image(tag_crop.convert("L"), 3), config="--psm 7")
    pos = re.search(r"\b([A-Z]{1,4})\b", tag)
    num = re.search(r"#\s*(\d{1,2})", tag)
    game = next((ln["text"] for ln in lines if re.match(r"^(vs|at)\b", ln["text"])), None)
    names = [ln["text"] for ln in lines if not re.match(r"^(vs|at)\b", ln["text"])][:2]
    stats = [ln["text"] for ln in lines if ln["y"] > max((x["y"] for x in lines if x["text"] == game), default=1e9)]
    last = names[1].replace("111", "III").title() if len(names) > 1 else ""
    last = re.sub(r"\b(Jr|Sr)\b\.?", r"\1.", re.sub(r"\b(Ii|Iii|Iv)\b", lambda m: m.group().upper(), last))
    result = re.search(r"\(([WL]) (\d+)-(\d+)\)", game or "")
    return {
        "name": f"{names[0]} {last}".strip() if names else None,
        "pos": fix.position(pos.group(1)) if pos else None,
        "number": int(num.group(1)) if num else None,
        "game": game,
        "result": {"outcome": result.group(1), "score": f"{result.group(2)}-{result.group(3)}"} if result else None,
        "stats": _stat_line(", ".join(stats)),
    }


def _stat_line(t: str) -> str:
    """'IOTKL, ITFL' -> '10 TKL, 1 TFL': I/O misread for 1/0 before a stat abbreviation."""
    t = re.sub(r"\b([IO0-9]+)(?=[A-Z]{2,})", lambda m: m.group(1).replace("I", "1").replace("O", "0") + " ", t)
    return re.sub(r"\s+", " ", t).strip()


def players_of_week(folder: Path, pool=None) -> list[dict]:
    parts = []
    for scope in sorted(folder.glob("conference*")):
        frame = scope / "frame.png"
        img = table.normalise(Image.open(frame))
        cards = {side: _card(img, box) for side, box in CARDS.items()}
        flags = [{"problem": f"{side} card incomplete", "read": c} for side, c in cards.items()
                 if not (c["name"] and c["game"] and c["stats"])]
        parts.append({"scope": snap(label(frame, LEFT_LABEL), CONFERENCES),
                      "week": label(frame, POTW_WEEK).title(), **cards, "flags": flags})
    fill_in_order(parts, "scope", POTW_SCOPES)
    return parts


POTW_SCOPES = ["National", "ACC", "American", "Big 12", "Big Ten", "CUSA", "Independent", "MAC", "MW",
               "Pac-12", "SEC", "Sun Belt"]


MEMBER_LIST = (0.035, 0.205, 0.29, 0.845)
CARD_PITCH = 125                              # px between member cards


def members(folder: Path, pool=None) -> list[dict]:
    known = fix.members()
    out, flags = [], []
    for frame in sorted(folder.glob("col*_row*.png")):
        img = table.normalise(Image.open(frame))
        lines = _box(img, MEMBER_LIST)
        # A card starts at its gamertag line; game and progress lines follow it. Lines
        # before the first gamertag belong to a card cut off at the top: skip them.
        cards = []
        for ln in (ln for ln in lines if ln["x"] > 100):
            t = ln["text"]
            detail = re.match(r"^(vs|at|W|L|@|---)\b", t, re.I) or re.search(r"\d+/\d+", t)
            if not detail and not t.lower().startswith("invite"):
                cards.append({"y": ln["y"], "tag": t, "rest": []})
            elif cards and detail:
                cards[-1]["rest"].append(t)
        rank_lines = [ln for ln in lines if ln["x"] < 60 and ln["text"].isdigit()]
        for c in cards:
            if not c["rest"]:
                continue                               # cut off at the bottom; seen in the next frame
            tag = fix.member(c["tag"], known)
            if any(m["gamertag"] == tag for m in out):
                continue
            rank = next((int(r["text"]) for r in rank_lines if abs(r["y"] - c["y"]) < 30), None)
            if rank is None:                           # small number, often missed on the highlighted card
                x0 = int(MEMBER_LIST[0] * 1920)
                y0 = int(MEMBER_LIST[1] * 1080 + c["y"])
                cell = img.crop((x0, y0 - 14, x0 + 50, y0 + 22)).convert("L")
                d = re.sub(r"\D", "", pytesseract.image_to_string(
                    table._ink_image(cell, 3), config="--psm 7 -c tessedit_char_whitelist=0123456789"))
                rank = int(d) if d and 1 <= int(d) <= 25 else None
            game = next((t for t in c["rest"] if re.match(r"^(vs|at|W|L)\b", t)), None)
            progress = next((m.group() for t in c["rest"] if (m := re.search(r"\d+/\d+", t))), None)
            if known and tag not in known:
                flags.append({"problem": "gamertag not in members.txt", "read": c["tag"]})
            out.append({"gamertag": tag, "team_rank": rank, "game": fix.text(game) if game else None,
                        "progress": progress, "team": None})
    return [{"rows": out, "flags": flags}]
