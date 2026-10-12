"""Config, screen recognition, navigation and per-screen capture.

Navigation model: every route starts at the Dynasty hub (the L1/R1 tab bar with
Actions, Members, ... Dynasty Central). To reach a screen we back out to the hub,
press R1 until the hub tab the route was taught from is selected, then replay the
taught key presses and check the screen title against a reference image.
"""

import json
from pathlib import Path

import numpy as np
from PIL import Image

from .stream import Stream
from .table import TableWalker

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
REFS = ROOT / "refs"

REGION_DELTA = 40                # grey-level change that counts as a changed pixel
REGION_MATCH = 0.02              # at most this fraction changed = same region
MAX_BACK = 8                     # Circle presses allowed when backing out to the hub


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


class Navigator:
    def __init__(self, stream: Stream, cfg: dict):
        self.s, self.cfg = stream, cfg
        hub = cfg["hub"]
        self.hub_box = hub["tab_box"]
        self.hub_refs = [Image.open(ref_path(f"hub_tab{i:02d}")) for i in range(hub.get("tabs", 0))]

    def hub_tab(self, frame) -> int | None:
        """Which hub tab is showing, or None if this isn't the hub."""
        for i, ref in enumerate(self.hub_refs):
            if region_matches(frame, ref, self.hub_box):
                return i
        return None

    def to_hub(self):
        """Back out (Circle) until the hub shows. Returns (frame, fkey, tab index)."""
        if not self.hub_refs:
            raise RuntimeError("The hub hasn't been taught yet. Run: python -m capture teach hub")
        frame, fk = self.s.settle()
        for _ in range(MAX_BACK + 1):
            tab = self.hub_tab(frame)
            if tab is not None:
                return frame, fk, tab
            _, frame, fk = self.s.press_and_wait("circle", fk)
        raise RuntimeError("Couldn't get back to the Dynasty hub by pressing Circle.")

    def goto(self, name: str):
        screen = self.cfg["screens"][name]
        if not screen.get("route_taught"):
            raise RuntimeError(f"No route for '{name}' yet. Run: python -m capture teach {name}")
        frame, fk, tab = self.to_hub()
        want = screen["hub_tab"]
        wraps = self.cfg["hub"].get("wraps", True)
        for _ in range(len(self.hub_refs)):
            if tab == want:
                break
            button = "r1" if wraps or tab < want else "l1"
            _, frame, fk = self.s.press_and_wait(button, fk)
            tab = self.hub_tab(frame)
        if tab != want:
            raise RuntimeError(f"Couldn't select hub tab {want} for '{name}'.")
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
