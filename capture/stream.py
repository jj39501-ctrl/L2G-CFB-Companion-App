"""Grab the game picture and press buttons, waiting for the stream to catch up."""

import time

import mss
import numpy as np
from PIL import Image
from pynput.keyboard import Controller, Key

from .display import Display

# Timing. The stream lags a key press by ~0.2s, and some updates (e.g. the column
# highlight on stats tables) land in a second stage ~0.8s later.
POLL = 0.05                      # seconds between grabs while waiting
CHANGE_TIMEOUT = 1.2             # no change within this long = the press did nothing
SETTLE_QUIET = 0.3               # screen must hold still this long to count as settled
SETTLE_TIMEOUT = 3.0             # give up waiting for stillness after this long

# Whole-frame comparison. A still stream grabs pixel-identical frames, and one
# column-cursor step changes ~0.07% of pixels, so this sits well below that.
FRAME_DELTA = 25                 # grey-level change that counts as a changed pixel
FRAME_CHANGED = 0.0001           # fraction of changed pixels = "something moved"


def key_for(name: str):
    """'down' -> Key.down, 'backspace' -> Key.backspace, 'q' -> 'q'."""
    return getattr(Key, name) if len(name) > 1 else name


def frame_key(frame: Image.Image) -> np.ndarray:
    g = frame.convert("L")
    g = g.resize((g.width // 4, g.height // 4))
    return np.asarray(g, dtype=np.int16)


def frame_diff(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return 1.0
    return float((np.abs(a - b) > FRAME_DELTA).mean())


class Stream:
    def __init__(self, display: Display, keymap: dict):
        self.display = display
        self.keymap = keymap         # PS button name -> keyboard key name (chiaki mapping)
        self.kb = Controller()
        self.sct = mss.MSS()

    def close(self):
        self.sct.close()

    def grab(self) -> Image.Image:
        shot = self.sct.grab(self.display.video.as_mss())
        return Image.frombytes("RGB", shot.size, shot.rgb)

    def press(self, button: str, hold: float = 0.08):
        key = key_for(self.keymap.get(button, button))
        self.kb.press(key)
        time.sleep(hold)
        self.kb.release(key)

    def settle(self, frame=None):
        """Keep grabbing until the screen holds still for SETTLE_QUIET. Returns (frame, fkey)."""
        if frame is None:
            frame = self.grab()
        fk = frame_key(frame)
        deadline = time.time() + SETTLE_TIMEOUT
        quiet_since = time.time()
        while time.time() < deadline and time.time() - quiet_since < SETTLE_QUIET:
            time.sleep(POLL)
            cur = self.grab()
            ck = frame_key(cur)
            if frame_diff(ck, fk) > FRAME_CHANGED:
                quiet_since = time.time()
            frame, fk = cur, ck
        return frame, fk

    def press_and_wait(self, button: str, fk):
        """Press, then wait for the stream to show the result.

        Returns (moved, frame, fkey). moved=False means nothing changed on screen.
        """
        self.press(button)
        deadline = time.time() + CHANGE_TIMEOUT
        cur, ck = None, fk
        while time.time() < deadline:
            time.sleep(POLL)
            cur = self.grab()
            ck = frame_key(cur)
            if frame_diff(ck, fk) > FRAME_CHANGED:
                return (True, *self.settle(cur))
        return False, cur, ck
