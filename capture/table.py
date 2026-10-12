"""Walk a scrolling table top-to-bottom and left-to-right, one frame per screenful.

Down/Right first move a cursor; once it reaches the visible edge, each press
scrolls the table one row/column. We count those scroll steps (the highlight bar
is normalised away so cursor moves don't count, see body_key) and save a frame
every rows_per_page / cols_per_page steps, so consecutive frames overlap by one.
"""

from pathlib import Path

import numpy as np
from PIL import Image

from .stream import Stream

STUCK_LIMIT = 2                  # presses with no effect before we call it the edge
TEXT_LEVEL = 150                 # grey level above which a (normalised) pixel is text
PIXEL_DELTA = 40                 # grey-level change that counts as a changed pixel
CHANGED_FRACTION = 0.002         # fraction of changed pixels that means "new content"
OPPOSITE = {"down": "up", "up": "down"}


def body_key(frame: Image.Image, body_box) -> np.ndarray:
    """Black/white text of the table body, with the highlight bar made to look normal.

    The highlighted row is dark text on a light bar; every other row is light text
    on dark. Inverting any pixel line whose median is light makes the two match, so
    moving the highlight alone doesn't register as new content.
    """
    w, h = frame.size
    l, t, r, b = body_box
    crop = frame.crop((int(l * w), int(t * h), int(r * w), int(b * h))).convert("L")
    crop = crop.resize((max(crop.width // 2, 1), max(crop.height // 2, 1)))
    a = np.asarray(crop, dtype=np.int16).copy()
    light = np.median(a, axis=1) > 128
    a[light] = 255 - a[light]
    return np.where(a > TEXT_LEVEL, 255, 0).astype(np.int16)   # keep only the text


def same_body(a: np.ndarray, b: np.ndarray) -> bool:
    if a.shape != b.shape:
        return False
    return (np.abs(a - b) > PIXEL_DELTA).mean() <= CHANGED_FRACTION


class TableWalker:
    def __init__(self, stream: Stream, spec: dict, max_presses: int = 400):
        self.s = stream
        self.body_box = spec["body_box"]
        self.rows_per_page = spec.get("rows_per_page", 11)
        self.cols_per_page = spec.get("cols_per_page", 9)
        self.horizontal = spec.get("horizontal", True)
        self.max_presses = max_presses

    def _bk(self, frame):
        return body_key(frame, self.body_box)

    def go_home(self, fk):
        """Press Up, then Left, until each stops moving."""
        for button in ("up", "left") if self.horizontal else ("up",):
            stuck = 0
            for _ in range(self.max_presses):
                moved, _, fk = self.s.press_and_wait(button, fk)
                stuck = 0 if moved else stuck + 1
                if stuck >= STUCK_LIMIT:
                    break
        return self.s.settle()

    def vertical_pass(self, direction, frame, fk):
        """Scroll one way to the end, collecting a frame per screenful (top first)."""
        bk = self._bk(frame)
        pages = [frame]
        scrolled, stuck = 0, 0
        for _ in range(self.max_presses):
            moved, frame, fk = self.s.press_and_wait(direction, fk)
            if not moved:
                stuck += 1
                if stuck >= STUCK_LIMIT:
                    break
                continue
            stuck = 0
            nbk = self._bk(frame)
            if not same_body(nbk, bk):                 # table scrolled, not just the highlight
                scrolled += 1
            bk = nbk
            if scrolled >= self.rows_per_page:
                pages.append(frame)
                scrolled = 0
        if scrolled:
            pages.append(frame)                        # the last, partial screenful
        if direction == "up":
            pages.reverse()
        return frame, fk, pages

    def step_right(self, frame, fk):
        """Press Right until a new screenful of columns is in view. None = right edge."""
        bk = self._bk(frame)
        scrolled, stuck = 0, 0
        for _ in range(self.max_presses):
            moved, frame, fk = self.s.press_and_wait("right", fk)
            if not moved:
                stuck += 1
                if stuck >= STUCK_LIMIT:
                    break
                continue
            stuck = 0
            nbk = self._bk(frame)
            if not same_body(nbk, bk):
                scrolled += 1
            bk = nbk
            if scrolled >= self.cols_per_page:
                return frame, fk
        return (frame, fk) if scrolled else None       # partial last page, or nothing new

    def walk(self, out_dir: Path, max_cols: int = 20) -> list[Path]:
        """Capture the whole table into out_dir as colNN_rowMM.png. Returns the files."""
        out_dir.mkdir(parents=True, exist_ok=True)
        frame, fk = self.s.settle()
        frame, fk = self.go_home(fk)
        files, direction = [], "down"
        for col in range(max_cols):
            frame, fk, pages = self.vertical_pass(direction, frame, fk)
            for i, page in enumerate(pages):
                path = out_dir / f"col{col:02d}_row{i:02d}.png"
                page.save(path)
                files.append(path)
            direction = OPPOSITE[direction]
            if not self.horizontal:
                break
            nxt = self.step_right(frame, fk)
            if nxt is None:
                break
            frame, fk = nxt
        return files
