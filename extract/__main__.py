"""python -m extract [--only screen,screen] [capture_dir ...]

OCR the latest capture of each screen (from the given capture folders, or all of
captures/) into data/<screen>.json, plus data/review.json listing anything that
didn't read cleanly. --only re-extracts just those screens (others keep their data).
"""

import argparse
import json
import time
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import link, screens, stats

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXTRACTORS = {
    "season_stats": lambda folder, pool: stats.fill_positions(
        [stats.extract_category(c, pool) for c in sorted(folder.glob("category*"))]),
    "top25": screens.top25,
    "standings": screens.standings,
    "schedule": screens.schedule,
    "heisman_watch": screens.heisman_watch,
    "players_of_week": screens.players_of_week,
    "members": screens.members,
}


def latest_captures(dirs: list[Path]) -> dict[str, tuple[Path, str]]:
    """screen -> (its folder in the newest capture that has it, captured_at)."""
    found = {}
    for run in sorted(dirs):
        manifest = run / "manifest.json"
        if manifest.exists():
            meta = json.loads(manifest.read_text(encoding="utf-8"))
            screens_found = [s for s, files in meta["screens"].items() if files]
            captured_at = meta["captured_at"]
        else:
            # A run stopped before writing its manifest: use what it saved, timed by its name.
            screens_found = [d.name for d in run.iterdir() if d.is_dir() and any(d.rglob("*.png"))]
            captured_at = datetime.strptime(run.name, "%Y-%m-%d_%H%M%S").isoformat()
        for screen in screens_found:
            found[screen] = (run / screen, captured_at)
    return found


def main():
    ap = argparse.ArgumentParser(prog="python -m extract")
    ap.add_argument("dirs", nargs="*", type=Path)
    ap.add_argument("--only", help="comma-separated screens to re-extract")
    args = ap.parse_args()
    dirs = args.dirs or [d for d in (ROOT / "captures").iterdir() if d.is_dir()]
    only = set(args.only.split(",")) if args.only else None
    DATA.mkdir(exist_ok=True)

    results, meta = {}, {}
    with ProcessPoolExecutor(4) as pool:
        for screen, (folder, captured_at) in latest_captures(dirs).items():
            if screen not in EXTRACTORS or (only and screen not in only):
                continue
            t0 = time.time()
            results[screen] = EXTRACTORS[screen](folder, pool)
            meta[screen] = {"captured_at": captured_at, "source": folder.parent.name}
            print(f"{screen}: {len(results[screen])} part(s), {time.time() - t0:.0f}s", flush=True)

    # Links span screens: load the saved data of screens not re-extracted this time,
    # link everything, and rewrite all of them (a new Top 25 updates schedule ranks).
    extracted = set(results)
    for screen in EXTRACTORS:
        path = DATA / f"{screen}.json"
        if screen not in results and path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            results[screen] = saved["data"]
            meta[screen] = {"captured_at": saved["captured_at"], "source": saved["source"]}
    link.ranks_from_top25(results)
    link.member_teams(results)

    review_path = DATA / "review.json"
    review = json.loads(review_path.read_text(encoding="utf-8")) if review_path.exists() else {}
    for screen in meta:
        flags = [f for part in results[screen] for f in part.pop("flags", [])]
        if screen in extracted or flags:
            review[screen] = flags
        out = {"screen": screen, **meta[screen], "data": results[screen]}
        (DATA / f"{screen}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        print(f"  {screen}: {len(flags)} to review")
    review_path.write_text(json.dumps(review, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
