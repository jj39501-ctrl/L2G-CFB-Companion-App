"""Capture, extract and publish the dynasty data to the site.

    python tools/publish.py --capture  # capture every screen, extract, commit data/, push
    python tools/publish.py            # extract the latest captures, commit, push
    python tools/publish.py --no-extract

Pushing to main triggers the GitHub Pages workflow, which rebuilds the site.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIT = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"


def run(*cmd):
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", action="store_true",
                    help="first capture every screen from chiaki-ng (keep off the controller)")
    ap.add_argument("--no-extract", action="store_true")
    args = ap.parse_args()
    if args.capture:
        print("Capturing every screen. Leave the controller and keyboard alone until it's done.")
        run(sys.executable, "-m", "capture", "run", "--fix")
    if not args.no_extract:
        run(sys.executable, "-m", "extract")
    review = json.loads((ROOT / "data" / "review.json").read_text(encoding="utf-8"))
    n = sum(len(v) for v in review.values())
    if n:
        print(f"Note: {n} item(s) in data/review.json; publishing anyway.")
    run(GIT, "add", "data")
    if subprocess.run([GIT, "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        print("No data changes to publish.")
        return
    week = json.loads((ROOT / "data" / "schedule.json").read_text(encoding="utf-8"))["data"][0].get("week", "")
    run(GIT, "commit", "-m", f"Update dynasty data ({week})".replace(" ()", ""))
    run(GIT, "push")
    print("Pushed. The site rebuilds in a minute or two:")
    print("  https://jj39501-ctrl.github.io/L2G-CFB-Companion-App/")


if __name__ == "__main__":
    main()
