"""Record one manual session: every controller/keyboard press plus a screenshot each
time the screen settles. F8 starts and stops; F9 aborts.

Output: recordings/<timestamp>/session.json and frames/NNNN.jpg. The session is
analysed afterwards to build routes, tab cycles and table layouts in config.json.
"""

import json
import threading
import time
from datetime import datetime

from . import screens
from .stream import FRAME_CHANGED, POLL, Stream, frame_diff, frame_key
from .teach import ABORT, MARK, Keys

QUIET = 0.35                     # screen must hold still this long before a frame is saved


def _frame_thread(stream: Stream, out, frames: list, t0: float, stop: threading.Event):
    """Save a frame whenever the screen settles into something new."""
    last_saved = None
    prev = frame_key(stream.grab())
    still_since = time.time()
    while not stop.is_set():
        time.sleep(POLL)
        img = stream.grab()
        k = frame_key(img)
        if frame_diff(k, prev) > FRAME_CHANGED:
            still_since = time.time()
        elif time.time() - still_since >= QUIET and (
                last_saved is None or frame_diff(k, last_saved) > FRAME_CHANGED):
            name = f"{len(frames):04d}.jpg"
            img.save(out / name, quality=95)
            frames.append({"t": round(still_since - t0, 2), "file": f"frames/{name}"})
            last_saved = k
        prev = k


def record(stream: Stream):
    out = screens.ROOT / "recordings" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    (out / "frames").mkdir(parents=True)
    presses, frames = [], []
    stop = threading.Event()

    with Keys() as keys:
        print("Press F8 to start recording (F9 aborts).", flush=True)
        keys.wait_mark()
        t0 = time.time()
        worker = threading.Thread(target=_frame_thread,
                                  args=(stream, out / "frames", frames, t0, stop), daemon=True)
        worker.start()
        print("Recording. Go through the screens with the controller; press F8 when done.",
              flush=True)
        keys.drain()
        try:
            while True:
                key = keys.q.get()
                if key == MARK:
                    break
                if key == ABORT:
                    raise SystemExit("Aborted (F9).")
                t = round(time.time() - t0, 2)
                presses.append({"t": t, "button": key})
                print(f"  {t:7.2f}s  {key:9}  ({len(frames)} frames)", flush=True)
        finally:
            time.sleep(QUIET + 0.2)  # let the last screen land
            stop.set()
            worker.join(2)

    d = stream.display
    session = {
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "picture": {"width": d.video.width, "height": d.video.height},
        "presses": presses,
        "frames": frames,
    }
    (out / "session.json").write_text(json.dumps(session, indent=1) + "\n", encoding="utf-8")
    print(f"Saved {len(presses)} presses and {len(frames)} frames to {out}")
