"""python -m extract [capture_dir ...]

OCR the latest capture of each screen (from the given capture folders, or all of
captures/) into data/<screen>.json, plus data/review.json listing anything that
didn't read cleanly.
"""

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import stats

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXTRACTORS = {
    "season_stats": lambda folder, pool: [stats.extract_category(c, pool)
                                          for c in sorted(folder.glob("category*"))],
}


def latest_captures(dirs: list[Path]) -> dict[str, tuple[Path, str]]:
    """screen -> (its folder in the newest capture that has it, captured_at)."""
    found = {}
    for run in sorted(dirs):
        manifest = run / "manifest.json"
        if not manifest.exists():
            continue
        meta = json.loads(manifest.read_text(encoding="utf-8"))
        for screen, files in meta["screens"].items():
            if files:
                found[screen] = (run / screen, meta["captured_at"])
    return found


def main():
    dirs = [Path(a) for a in sys.argv[1:]] or [d for d in (ROOT / "captures").iterdir() if d.is_dir()]
    DATA.mkdir(exist_ok=True)
    review = {}
    with ProcessPoolExecutor(4) as pool:
        for screen, (folder, captured_at) in latest_captures(dirs).items():
            if screen not in EXTRACTORS:
                print(f"{screen}: no extractor yet, skipped")
                continue
            t0 = time.time()
            result = EXTRACTORS[screen](folder, pool)
            flags = [f for part in result for f in part.pop("flags", [])]
            out = {"screen": screen, "captured_at": captured_at, "source": folder.parent.name,
                   "data": result}
            (DATA / f"{screen}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
            review[screen] = flags
            print(f"{screen}: {len(result)} part(s), {len(flags)} to review, {time.time() - t0:.0f}s",
                  flush=True)
    (DATA / "review.json").write_text(json.dumps(review, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
