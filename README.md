# CFB Dynasty Companion

A read-only companion site for an online College Football 27 dynasty, in the spirit
of Neon Sportz / Madden companion apps. Data comes from the game itself: a script
drives a [chiaki-ng](https://github.com/streetpea/chiaki-ng) Remote Play stream on a
Windows PC, screenshots each dynasty screen, and OCR turns them into JSON for the site.

```
capture/   drive chiaki-ng and screenshot dynasty screens   (working)
extract/   OCR screenshots into JSON                         (next)
site/      static site on GitHub Pages                        (later)
```

## Setup

```bash
pip install -r requirements.txt
```

Open chiaki-ng, connect to the PS5, and maximize the stream window. Leave chiaki-ng on
its default keyboard mapping (or update `keymap` in `config.json`).

## Capturing

```bash
python -m capture check          # window/monitor/scaling check (add --fix to maximize)
python -m capture teach hub      # once: record the Dynasty hub tabs
python -m capture teach top25    # once per screen: record how to get there
python -m capture run            # visit and capture every taught screen
python -m capture here season_stats   # capture whatever's on screen now
```

Captures land in `captures/<timestamp>/<screen>/...` with a `manifest.json`.

### How it works

- **Display check.** Finds the chiaki-ng window, its monitor and display scaling, and
  where the 16:9 game picture sits inside the window. Every layout box in
  `config.json` is a fraction of that picture, so any window size or monitor works.
- **Teach mode.** You drive chiaki-ng by hand from the Dynasty hub to a screen and
  press F8; the script records the keys and a reference image of the screen title.
- **Run.** Backs out to the hub with Circle, selects the right hub tab, replays the
  route, checks the title matches the reference, then captures.
- **Tables** (stats, members) are walked top-to-bottom and left-to-right, saving one
  frame per screenful with one row/column of overlap. Screens with `tabs` (e.g. stat
  categories on R2) are cycled until the tab wraps back to the first.
- Close Windows notifications (or turn on Do Not Disturb) while capturing: anything
  drawn over the stream ends up in the screenshots.
