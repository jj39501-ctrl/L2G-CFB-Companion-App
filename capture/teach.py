"""Teach mode: you drive chiaki-ng by hand while we record keys and reference images.

F8 marks each step ("I'm here"); F9 aborts. Keys go to chiaki as normal; we only
listen. The keys you press also teach us chiaki's keyboard mapping (R1, Circle).
"""

import queue
import time

from pynput import keyboard

from . import screens
from .stream import Stream

MARK, ABORT = "f8", "f9"
DEFAULT_VERIFY_BOX = [0.02, 0.02, 0.45, 0.10]   # screen title, top-left


def _name(key) -> str:
    if isinstance(key, keyboard.Key):
        return key.name
    if key.char:
        return key.char.lower()
    return f"vk{key.vk}"


class Keys:
    """Background listener feeding key names into a queue."""

    def __init__(self):
        self.q: queue.Queue[str] = queue.Queue()
        self.listener = keyboard.Listener(on_press=lambda k: self.q.put(_name(k)))

    def __enter__(self):
        self.listener.start()
        return self

    def __exit__(self, *exc):
        self.listener.stop()

    def next(self) -> str:
        key = self.q.get()
        if key == ABORT:
            raise SystemExit("Aborted (F9). Nothing was saved.")
        return key

    def wait_mark(self):
        while self.next() != MARK:
            pass

    def drain(self):
        while not self.q.empty():
            self.q.get()


def _after_key(stream: Stream):
    time.sleep(0.4)                  # let the stream show the press before settling
    return stream.settle()[0]


def teach_hub(stream: Stream, cfg: dict):
    hub = cfg["hub"]
    with Keys() as keys:
        print("In chiaki-ng, go to the Dynasty hub (the screen with the L1/R1 tab bar:\n"
              "Actions, Members, ... Dynasty Central). Select the FIRST tab (Actions),\n"
              "then press F8.  (F9 aborts.)")
        keys.wait_mark()
        screens.REFS.mkdir(exist_ok=True)
        first = stream.settle()[0]
        first.save(screens.ref_path("hub_tab00"))
        refs = [first]
        print("Now press R1 once at a time to step through every tab. Stop when you're\n"
              "back on Actions (or press F8 if the tabs don't wrap around).")
        keys.drain()
        r1_key, wraps = None, False
        while True:
            key = keys.next()
            if key == MARK:
                break
            frame = _after_key(stream)
            r1_key = r1_key or key
            if screens.region_matches(frame, first, hub["tab_box"]):
                wraps = True
                break
            if any(screens.region_matches(frame, r, hub["tab_box"]) for r in refs):
                continue                                # nothing changed; ignore
            frame.save(screens.ref_path(f"hub_tab{len(refs):02d}"))
            refs.append(frame)
            print(f"  tab {len(refs) - 1} recorded")
    hub["tabs"] = len(refs)
    hub["wraps"] = wraps
    if r1_key:
        cfg["keymap"]["r1"] = r1_key
    screens.save_config(cfg)
    print(f"Hub taught: {len(refs)} tabs, R1 is the '{r1_key}' key, "
          f"{'wraps around' if wraps else 'does not wrap'}.")


def teach_screen(stream: Stream, cfg: dict, name: str):
    if name not in cfg["screens"]:
        cfg["screens"][name] = {"mode": "single"}
    screen = cfg["screens"][name]
    nav = screens.Navigator(stream, cfg)
    reverse = {v: k for k, v in cfg["keymap"].items()}

    with Keys() as keys:
        print(f"Teaching '{name}'.\nIn chiaki-ng, go to the Dynasty hub (any tab), then press F8.")
        keys.wait_mark()
        tab = nav.hub_tab(stream.settle()[0])
        if tab is None:
            raise SystemExit("That doesn't look like the Dynasty hub. Run 'teach hub' again if "
                             "the hub has changed.")
        print(f"  hub tab {tab}. Now navigate to {name} with the keyboard, then press F8.")
        keys.drain()
        route = []
        while (key := keys.next()) != MARK:
            route.append(reverse.get(key, key))
        frame = stream.settle()[0]
        frame.save(screens.ref_path(name))
        print(f"  recorded {len(route)} presses: {' '.join(route)}")

        print("Now press Circle (Back) until you're on the hub again, then press F8.")
        keys.drain()
        back_key = None
        while (key := keys.next()) != MARK:
            back_key = back_key or key
        if nav.hub_tab(stream.settle()[0]) is None:
            print("  warning: that doesn't look like the hub; Circle mapping not saved.")
        elif back_key:
            cfg["keymap"]["circle"] = back_key

    screen.update(route=route, hub_tab=tab, route_taught=True)
    screen.setdefault("verify_box", DEFAULT_VERIFY_BOX)
    screens.save_config(cfg)
    print(f"Saved route for '{name}' and its reference image refs/{name}.png.")
