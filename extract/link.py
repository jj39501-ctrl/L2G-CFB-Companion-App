"""Cross-screen links, run after every screen is extracted.

Member cards show a team logo (not text), the team's ranking and the member's game
this week, e.g. "at 18 Notre Dame". The schedule names both teams of every game, so
the member's team is the other side of their game. When several teams play the same
opponent (FCS teams), the card's ranking against the Top 25 picks between them.
"""

import re

from . import fix


def ranks_from_top25(results: dict):
    """Rankings shown next to team names (schedule, standings, Heisman) are just the
    current Top 25, which is extracted cleanly; the small numbers beside logos often
    aren't. So take every such ranking from the poll."""
    poll = results.get("top25")
    if not poll:
        return
    rank = {r["team"]: r["rank"] for r in poll[0]["rows"]}
    for part in results.get("schedule") or []:
        seen, games = set(), []
        for g in part["games"]:
            g["away_rank"], g["home_rank"] = rank.get(g["away"]), rank.get(g["home"])
            if (g["away"], g["home"]) not in seen:          # a row read twice with different junk
                seen.add((g["away"], g["home"]))
                games.append(g)
        part["games"] = games
    for part in results.get("standings") or []:
        for r in part["rows"]:
            r["rank"] = rank.get(r["team"])
    for part in results.get("heisman_watch") or []:
        for r in part["rows"]:
            r["team_rank"] = rank.get(r["team"])


def _opponent(game: str):
    """(opponent, side) where side is 'away' (member plays at the opponent), 'home', or None
    when the at/vs was lost."""
    m = re.search(r"\b(at|vs)\b(.*)$", game)
    if m:
        rank, name, known = fix.team(m.group(2))
        if known:
            return name, ("away" if m.group(1) == "at" else "home")
    found = fix.find_teams(game)
    if found:
        return found[-1][1], None
    rank, name, known = fix.team(re.sub(r"^[WL]\s+[\d\-\s]*", "", game))
    return (name, None) if known else (None, None)


def member_teams(results: dict):
    members = results.get("members")
    sched = results.get("schedule")
    if not members or not sched:
        return
    games = sched[0]["games"]
    by_rank = {r["rank"]: r["team"] for r in (results.get("top25") or [{"rows": []}])[0]["rows"]}
    part = members[0]
    pending = []
    for m in part["rows"]:
        game = m.get("game") or ""
        opponent, side = _opponent(game)
        candidates = []
        if opponent:
            for g in games:
                if side in ("away", None) and g["home"] == opponent:
                    candidates.append((g["away"], False))
                if side in ("home", None) and g["away"] == opponent:
                    candidates.append((g["home"], True))
            m["opponent"] = opponent
        ranked = by_rank.get(m.get("team_rank"))
        if len(candidates) > 1 and ranked:
            candidates = [c for c in candidates if c[0] == ranked] or candidates
        if len(candidates) == 1:
            m["team"], m["home"] = candidates[0]
        elif not candidates and ranked and not opponent:
            m["team"] = ranked                                   # bye week: rank alone
        else:
            pending.append((m, candidates))
    # Last resort: drop teams other members already have.
    taken = {m["team"] for m in part["rows"] if m.get("team")}
    for m, candidates in pending:
        left = [c for c in candidates if c[0] not in taken]
        if len(left) == 1:
            m["team"], m["home"] = left[0]
            taken.add(left[0][0])
        else:
            part["flags"].append({"problem": "couldn't work out member's team", "member": m["gamertag"],
                                  "read": m.get("game"), "candidates": [c[0] for c in candidates]})
    for m in part["rows"]:
        rank = next((r for r, t in by_rank.items() if t == m.get("team")), None)
        if m.get("team_rank") is None:
            m["team_rank"] = rank
