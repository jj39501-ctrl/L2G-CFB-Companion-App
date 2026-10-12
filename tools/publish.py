"""Extract the latest captures and publish them to the site.

    python tools/publish.py            # extract all screens, commit data/, push
    python tools/publish.py --no-extract

Pushing to main triggers the GitHub Pages workflow, which rebuilds the site.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*cmd):
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-extract", action="store_true")
    args = ap.parse_args()
    if not args.no_extract:
        run(sys.executable, "-m", "extract")
    review = json.loads((ROOT / "data" / "review.json").read_text(encoding="utf-8"))
    n = sum(len(v) for v in review.values())
    if n:
        print(f"Note: {n} item(s) in data/review.json; publishing anyway.")
    run("git", "add", "data")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        print("No data changes to publish.")
        return
    week = json.loads((ROOT / "data" / "schedule.json").read_text(encoding="utf-8"))["data"][0].get("week", "")
    run("git", "commit", "-m", f"Update dynasty data ({week})".replace(" ()", ""))
    run("git", "push")
    print("Pushed. The site rebuilds in a minute or two.")


if __name__ == "__main__":
    main()
