"""Find the chiaki-ng window, check it's usable, and locate the game picture in it.

All layout boxes in config.json are fractions of the 16:9 game picture (0..1), not
of the window, so they hold for any window size, monitor or display scaling.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import numpy as np

# Per-monitor DPI awareness, before anything measures the screen. Without it, window
# positions and screenshot coordinates disagree on monitors with display scaling.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    pass

import mss  # noqa: E402  (must come after the DPI call)
import pywinctl  # noqa: E402
from PIL import Image  # noqa: E402

user32 = ctypes.windll.user32

MIN_VIDEO_HEIGHT = 720           # below this, small stat text gets hard to OCR
ASPECT = 16 / 9
BLACK_LEVEL = 12                 # grey level at or below which a pixel is letterbox black


@dataclass
class Rect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self):
        return self.left + self.width

    @property
    def bottom(self):
        return self.top + self.height

    def as_mss(self):
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}

    def __str__(self):
        return f"{self.width}x{self.height} at ({self.left},{self.top})"


@dataclass
class Display:
    hwnd: int
    title: str
    client: Rect                 # window client area, physical screen pixels
    video: Rect                  # the game picture inside the client area
    monitor: Rect
    scale: float                 # Windows display scaling of the window's monitor

    def box_px(self, box, size=None):
        """Picture-fraction box -> pixel box within a picture of `size` (default: live)."""
        w, h = size or (self.video.width, self.video.height)
        l, t, r, b = box
        return int(l * w), int(t * h), int(r * w), int(b * h)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def find_window(title_substr: str):
    wins = [w for w in pywinctl.getAllWindows()
            if title_substr.lower() in w.title.lower() and w.width > 0 and w.height > 0]
    if not wins:
        return None
    return max(wins, key=lambda w: w.width * w.height)   # the stream, not a folder named chiaki


def client_rect(hwnd) -> Rect:
    rc = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return Rect(pt.x, pt.y, rc.right - rc.left, rc.bottom - rc.top)


def monitor_of(hwnd) -> Rect:
    hmon = user32.MonitorFromWindow(hwnd, 2)   # MONITOR_DEFAULTTONEAREST
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    user32.GetMonitorInfoW(hmon, ctypes.byref(info))
    r = info.rcMonitor
    return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)


def fit_aspect(client: Rect) -> Rect:
    """Where a 16:9 picture lands when scaled to fit the client area (letter/pillarbox)."""
    if client.width / client.height > ASPECT:
        w, h = round(client.height * ASPECT), client.height
    else:
        w, h = client.width, round(client.width / ASPECT)
    return Rect(client.left + (client.width - w) // 2, client.top + (client.height - h) // 2, w, h)


def detect_picture(img: Image.Image):
    """Bounding box (l, t, r, b) of the non-black content, or None if it's all black."""
    a = np.asarray(img.convert("L"))
    rows = np.nonzero((a > BLACK_LEVEL).mean(axis=1) > 0.05)[0]
    cols = np.nonzero((a > BLACK_LEVEL).mean(axis=0) > 0.05)[0]
    if rows.size == 0 or cols.size == 0:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def preflight(title_substr: str, fix: bool = False):
    """Check the stream window is usable. Returns (Display or None, problems, notes).

    problems are blocking; notes are informational. With fix=True, a minimized or
    too-small window is restored/maximized first.
    """
    import time
    problems, notes = [], []

    win = find_window(title_substr)
    if win is None:
        return None, [f"No window with '{title_substr}' in its title. Is the stream open?"], notes
    hwnd = win.getHandle()

    if win.isMinimized:
        if not fix:
            return None, ["chiaki-ng is minimized. Restore it, or rerun with --fix."], notes
        win.restore()
        time.sleep(0.8)
        notes.append("Restored the minimized window.")

    win.activate()
    time.sleep(0.5)

    client = client_rect(hwnd)
    video = fit_aspect(client)
    if video.height < MIN_VIDEO_HEIGHT and not win.isMaximized and fix:
        win.maximize()
        time.sleep(0.8)
        client = client_rect(hwnd)
        video = fit_aspect(client)
        notes.append("Maximized the window to get a bigger picture.")

    monitor = monitor_of(hwnd)
    scale = user32.GetDpiForWindow(hwnd) / 96
    notes.append(f"Monitor {monitor}, display scaling {scale:.0%}.")
    notes.append(f"Window client area {client}; game picture {video}.")

    if video.height < MIN_VIDEO_HEIGHT:
        problems.append(f"Game picture is only {video.height}px tall (need {MIN_VIDEO_HEIGHT}+ "
                        "for reliable OCR). Maximize chiaki-ng, or rerun with --fix.")
    if (client.left < monitor.left or client.top < monitor.top
            or client.right > monitor.right or client.bottom > monitor.bottom):
        problems.append("Part of the chiaki-ng window is off its monitor, so it can't all be "
                        "captured. Maximize it on one screen.")
    if user32.GetForegroundWindow() != hwnd:
        problems.append("Couldn't bring chiaki-ng to the front (another window or a Windows "
                        "prompt is in the way). Key presses would go to the wrong place.")

    with mss.MSS() as sct:
        try:
            shot = sct.grab(client.as_mss())
        except mss.exception.ScreenShotError:
            problems.append("Screen capture is blocked. Is the PC locked or a UAC prompt open?")
            return None, problems, notes
    img = Image.frombytes("RGB", shot.size, shot.rgb)
    found = detect_picture(img)
    if found is None:
        problems.append("The stream is showing a black screen. Is the console connected?")
    else:
        l, t, r, b = found
        detected = Rect(client.left + l, client.top + t, r - l, b - t)
        # Trust detection over the aspect-fit maths when they disagree a lot (chiaki's
        # zoom/stretch modes), but only if it still looks like a 16:9 picture.
        off = max(abs(detected.left - video.left), abs(detected.top - video.top),
                  abs(detected.width - video.width), abs(detected.height - video.height))
        if off > 0.02 * video.width:
            if abs(detected.width / detected.height - ASPECT) < 0.03:
                notes.append(f"Picture detected at {detected} (not where 16:9 fit predicts); "
                             "using the detected area.")
                video = detected
            else:
                notes.append(f"Non-black content spans {detected}, which isn't 16:9; keeping the "
                             "computed picture area. (Dark screen edges can cause this.)")

    return Display(hwnd, win.title, client, video, monitor, scale), problems, notes
