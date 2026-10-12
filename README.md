# L2G CFB Companion

A read-only companion site for the L2G College Football 27 online dynasty, in the spirit
of Neon Sportz / Madden companion apps. The data comes from the game itself: a script
drives a [chiaki-ng](https://github.com/streetpea/chiaki-ng) Remote Play stream on a
Windows PC, screenshots each dynasty screen, and OCR turns the screenshots into JSON
that the site reads.

```
capture/   drive chiaki-ng and screenshot dynasty screens  -> captures/<timestamp>/
extract/   OCR the screenshots into JSON                    -> data/*.json
site/      the static site (no build step) that reads data/
tools/     build_site.py, publish.py, build_templates.py, pad_test.py
```

Screens: Season Stats (all 9 categories, national top 100), Scores/Schedule, Top 25,
Conference Standings, Players of the Week, Heisman Watch, Members.

## Weekly update

1. Open chiaki-ng, connect to the PS5, maximize the stream, go to the Dynasty hub.
2. Capture every screen (about 40 minutes; hands off the controller):
   ```
   python -m capture run
   ```
3. Extract and publish (about 5 minutes):
   ```
   python tools/publish.py
   ```
   This runs `python -m extract`, commits `data/` and pushes; GitHub Pages rebuilds
   the site. Anything that didn't read cleanly is listed in `data/review.json`.

## Setup (once)

```
pip install -r requirements.txt
winget install UB-Mannheim.TesseractOCR
```

Windows' built-in OCR engine (used for names and words) needs no install.

- `extract/teams.txt`: team names as the game shows them; OCR'd team text is snapped
  to this list. Add a line if `review.json` reports an unknown team.
- `extract/members.txt`: the league's gamertags; add new members here.
- `config.json`: routes and layouts for each screen (see capture below).

## Capture

```
python -m capture check          # window/monitor/scaling check (add --fix to maximize)
python -m capture record         # record a manual session (F8 start/stop) to derive routes
python -m capture run [screen]   # visit and capture screens
python -m capture here <screen>  # capture whatever is on screen now
```

- **Display check.** Finds the chiaki-ng window, its monitor and display scaling, and the
  16:9 game picture inside it. Every layout box in `config.json` is a fraction of that
  picture, so any window size or monitor works.
- **Navigation.** Every route starts at the Dynasty hub. The hub's tab is identified by
  where its highlight sits; the left-hand menu wraps, so items are selected by position
  (`@item:N`). Arrival is checked against a reference image of the screen title.
- **Tables** are walked top-to-bottom and left-to-right, one frame per screenful with a
  row/column of overlap. Tabbed screens cycle R2 (stat categories) or an L2 drop-down
  (conferences) until they wrap.
- Turn on Windows Do Not Disturb while capturing: anything drawn over the stream ends up
  in the screenshots.

## Extract

```
python -m extract                       # newest capture of each screen -> data/
python -m extract --only top25,members  # just these screens
```

- **Numbers** are read by matching the game's own digit shapes (`extract/templates`, cut
  from a hand-checked frame by `tools/build_templates.py`), with Windows OCR as a second
  opinion when it reads the same length. Decimal points, commas and minus signs are
  found by shape.
- **Names and words** use Windows OCR; short tags and text-with-scores use Tesseract.
- Pages are stitched on their overlapping rows/columns; player names and positions are
  voted across pages; rankings come from the Top 25; members are linked to their team
  through this week's schedule.

## Site

```
python tools/build_site.py && python -m http.server 8765 --directory _site
```

GitHub Actions (`.github/workflows/pages.yml`) builds and deploys on every push to `main`
that touches `site/` or `data/`.
