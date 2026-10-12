"""Print controller buttons as you press them, for 20 seconds (checks teach mode can see them)."""

import queue
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capture.teach import _pad_thread  # noqa: E402

q, stop = queue.Queue(), threading.Event()
threading.Thread(target=_pad_thread, args=(q, stop), daemon=True).start()
print("Click into chiaki-ng and press a few controller buttons (20 seconds)...", flush=True)
end = time.time() + 20
while time.time() < end:
    try:
        print("  pressed:", q.get(timeout=0.2), flush=True)
    except queue.Empty:
        pass
stop.set()
print("Done.")
