"""Assemble the static site: site/* plus data/*.json -> _site/ (what GitHub Pages serves).

review.json stays out: it's the OCR to-do list, not league data.
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "site", OUT)
    (OUT / "data").mkdir()
    for f in (ROOT / "data").glob("*.json"):
        if f.name != "review.json":
            shutil.copy2(f, OUT / "data" / f.name)
    (OUT / ".nojekyll").touch()
    print(f"Built {OUT} ({len(list((OUT / 'data').iterdir()))} data files)")


if __name__ == "__main__":
    main()
