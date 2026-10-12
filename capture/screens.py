"""Config, screen recognition, navigation and per-screen capture.

Navigation model: every route starts at the Dynasty hub (the L1/R1 tab bar with
Actions, Members, ... Dynasty Central). To reach a screen we back out to the hub,
press R1 until the hub tab the route was taught from is selected, then replay the
taught key presses and check the screen title against a reference image.
"""

import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .stream import Stream
from .table import TableWalker

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
REFS = ROOT / "refs"

REGION_DELTA = 40                # grey-level change that counts as a changed pixel
REGION_MATCH = 0.02              # at most this fraction changed = same region
MAX_BACK = 8                     # Circle presses allowed when backing out to the hub
HUB_WAIT = 3.0                   # seconds to wait for the hub to fade in before pressing again
MAX_TABS = 10                   # L1/R1 presses allowed when picking a hub tab
HIGHLIGHT_LEVEL = 200            # grey level of the selected tab's white box
MIN_HIGHLIGHT = 0.03             # narrowest highlight, as a fraction of the tab bar
TAB_TOLERANCE = 0.03             # how close two highlight centres must be to be one tab
COARSE_DELTA = 30                # grey-level change that counts, on the blurred 1/8 crop
COARSE_MATCH = 0.05              # hub tabs measure <=0.3% changed; other screens ~18%


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def region_key(img: Image.Image, box, size=None) -> np.ndarray:
    """Greyscale crop of a picture-fraction box, scaled to `size` so refs taken at a
    different window size still compare."""
    w, h = img.size
    l, t, r, b = box
    crop = img.crop((int(l * w), int(t * h), int(r * w), int(b * h))).convert("L")
    crop = crop.resize(size or (max(crop.width // 2, 1), max(crop.height // 2, 1)))
    return np.asarray(crop, dtype=np.int16)


def region_matches(img: Image.Image, ref: Image.Image, box) -> bool:
    a = region_key(img, box)
    b = region_key(ref, box, size=(a.shape[1], a.shape[0]))
    return float((np.abs(a - b) > REGION_DELTA).mean()) <= REGION_MATCH


def ref_path(name: str) -> Path:
    return REFS / f"{name}.png"


def highlight_span(img: Image.Image, box):
    """(start, end) of the selected tab's white box, as fractions of the box width.

    The selected tab is a solid white rectangle; columns that are mostly bright mark
    it. Returns the widest such run, or None if there's no highlight.
    """
    w, h = img.size
    l, t, r, b = box
    g = np.asarray(img.crop((int(l * w), int(t * h), int(r * w), int(b * h))).convert("L"))
    # Inside the box every column is >=30% bright even through the dark label text;
    # plain white tab labels are thin strokes and stay well under that.
    bright = (g > HIGHLIGHT_LEVEL).mean(axis=0) > 0.25
    best, start = None, None
    for x, on in enumerate(list(bright) + [False]):
        if on and start is None:
            start = x
        elif not on and start is not None:
            if best is None or x - start > best[1] - best[0]:
                best = (start, x)
            start = None
    if best is None or best[1] - best[0] < MIN_HIGHLIGHT * g.shape[1]:
        return None
    return best[0] / g.shape[1], best[1] / g.shape[1]


def _coarse(img: Image.Image, box) -> np.ndarray:
    """Blurred greyscale crop at a fixed 1/8-of-1794px-wide scale (window-size independent)."""
    w, h = img.size
    l, t, r, b = box
    crop = img.crop((int(l * w), int(t * h), int(r * w), int(b * h))).convert("L")
    crop = crop.filter(ImageFilter.GaussianBlur(3 * w / 1794))
    cw = max(round((r - l) * 1794 / 8), 1)
    ch = max(round((b - t) * 1009 / 8), 1)
    return np.asarray(crop.resize((cw, ch)), dtype=np.int16)


class Navigator:
    """Hub tabs are identified by where the highlight sits (centre, as a fraction of the
    tab bar), so any tab of the hub is recognised from one reference image."""

    def __init__(self, stream: Stream, cfg: dict):
        self.s, self.cfg = stream, cfg
        self.hub_box = cfg["hub"]["tab_box"]
        path = ref_path("hub")
        self.hub_ref = Image.open(path) if path.exists() else None

    def hub_tab(self, frame) -> float | None:
        """Centre of the selected hub tab, or None if this isn't the hub.

        It's the hub if the tab bar matches the reference everywhere except where
        either image has its highlight. Compared blurred and at 1/8 scale, because the
        other labels shift a few pixels depending on which tab is selected.
        """
        if self.hub_ref is None:
            return None
        span = highlight_span(frame, self.hub_box)
        ref_span = highlight_span(self.hub_ref, self.hub_box)
        if span is None or ref_span is None:
            return None
        a, b = _coarse(frame, self.hub_box), _coarse(self.hub_ref, self.hub_box)
        keep = np.ones(a.shape[1], dtype=bool)
        for s0, s1 in (span, ref_span):
            keep[int(s0 * a.shape[1]) - 1:int(s1 * a.shape[1]) + 2] = False
        if float((np.abs(a - b)[:, keep] > COARSE_DELTA).mean()) > COARSE_MATCH:
            return None
        return (span[0] + span[1]) / 2

    def to_hub(self):
        """Back out (Circle) until the hub shows. Returns (frame, fkey, tab centre)."""
        if self.hub_ref is None:
            raise RuntimeError("The hub hasn't been taught yet. Run: python -m capture teach hub")
        for _ in range(MAX_BACK + 1):
            # Menus fade in after a transition, so give the hub a moment to appear
            # before pressing Circle again (an extra Circle on the hub could open a prompt).
            deadline = time.time() + HUB_WAIT
            while True:
                frame, fk = self.s.settle()
                tab = self.hub_tab(frame)
                if tab is not None:
                    return frame, fk, tab
                if time.time() > deadline:
                    break
                time.sleep(0.3)
            self.s.press("circle")
        raise RuntimeError("Couldn't get back to the Dynasty hub by pressing Circle.")

    def goto(self, name: str):
        screen = self.cfg["screens"][name]
        if not screen.get("route_taught"):
            raise RuntimeError(f"No route for '{name}' yet. Run: python -m capture teach {name}")
        frame, fk, tab = self.to_hub()
        want = screen["hub_tab"]
        for _ in range(MAX_TABS):
            if abs(tab - want) <= TAB_TOLERANCE:
                break
            _, frame, fk = self.s.press_and_wait("r1" if want > tab else "l1", fk)
            tab = self.hub_tab(frame)
            if tab is None:
                raise RuntimeError("Lost the hub while switching tabs.")
        else:
            raise RuntimeError(f"Couldn't select the hub tab for '{name}'.")
        for button in screen["route"]:
            _, frame, fk = self.s.press_and_wait(button, fk)
        frame, fk = self.s.settle()
        if not region_matches(frame, Image.open(ref_path(name)), screen["verify_box"]):
            raise RuntimeError(f"Arrived somewhere that doesn't look like '{name}'.")
        return frame, fk


def capture_here(stream: Stream, screen: dict, out_dir: Path) -> list[Path]:
    """Capture the screen that's showing now, cycling its tabs if it has any."""
    files: list[Path] = []
    _cycle_tabs(stream, screen, screen.get("tabs", []), out_dir, files)
    return files


def _cycle_tabs(stream, screen, tabs, out_dir, files):
    if not tabs:
        files.extend(_capture_view(stream, screen, out_dir))
        return
    tab, rest = tabs[0], tabs[1:]
    frame, fk = stream.settle()
    first = frame
    for i in range(tab.get("max", 20)):
        print(f"    {tab['name']} {i}", flush=True)
        _cycle_tabs(stream, screen, rest, out_dir / f"{tab['name']}{i:02d}", files)
        moved, frame, fk = stream.press_and_wait(tab["button"], fk)
        if not moved or region_matches(frame, first, screen["tab_box"]):
            break                                      # only one tab, or wrapped to the first


def _capture_view(stream, screen, out_dir: Path) -> list[Path]:
    mode = screen.get("mode", "single")
    if mode == "table":
        return TableWalker(stream, screen["table"]).walk(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frame, _ = stream.settle()
    path = out_dir / "frame.png"
    frame.save(path)
    return [path]
