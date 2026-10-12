"""Teach mode: you drive chiaki-ng by hand while we record presses and reference images.

Drive with the PS5 controller or the keyboard. F8 (keyboard) marks each step
("I'm here"); F9 aborts. Input goes to chiaki as normal; we only listen.
Controller buttons are recorded by PS name (cross, r1, down, ...); replay sends
the matching keyboard key from config.json's keymap.
"""

import os
import queue
import threading
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


# SDL game-controller button numbers -> PS names. Triggers are axes, handled below.
PAD_BUTTONS = {0: "cross", 1: "circle", 2: "square", 3: "triangle", 4: "create", 5: "ps",
               6: "options", 7: "l3", 8: "r3", 9: "l1", 10: "r1", 11: "up", 12: "down",
               13: "left", 14: "right", 20: "touchpad"}
PAD_TRIGGERS = {4: "l2", 5: "r2"}
PS_NAMES = set(PAD_BUTTONS.values()) | set(PAD_TRIGGERS.values())
TRIGGER_ON = 16000               # of 32767: a trigger counts as pressed past about half


def _pad_thread(q: queue.Queue, stop: threading.Event):
    """Poll the first game controller and queue button names. Silent if there's none."""
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    # chiaki-ng has focus, not us; without this SDL drops controller events.
    os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"
    import pygame
    from pygame._sdl2 import controller

    pygame.display.init()            # SDL's input pump needs the video subsystem (no window)
    controller.init()
    if controller.get_count() == 0:
        return
    pad = controller.Controller(0)
    # Poll button states and report rising edges. (Waiting for SDL events missed
    # presses while chiaki-ng had focus.)
    held = set()
    while not stop.is_set():
        pygame.event.pump()
        down = {name for b, name in PAD_BUTTONS.items() if pad.get_button(b)}
        down |= {name for a, name in PAD_TRIGGERS.items()
                 if pad.get_axis(a) > (TRIGGER_ON if name not in held else TRIGGER_ON // 2)}
        for name in down - held:
            q.put(name)
        held = down
        time.sleep(0.01)
    pad.quit()


class Keys:
    """Background listeners (keyboard + controller) feeding input names into a queue."""

    def __init__(self):
        self.q: queue.Queue[str] = queue.Queue()
        self.listener = keyboard.Listener(on_press=lambda k: self.q.put(_name(k)))
        self.stop = threading.Event()
        self.pad = threading.Thread(target=_pad_thread, args=(self.q, self.stop), daemon=True)

    def __enter__(self):
        self.listener.start()
        self.pad.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
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


def teach_hub(stream: Stream, cfg: dict):
    with Keys() as keys:
        print("In chiaki-ng, go to the Dynasty hub (the screen with the L1/R1 tab bar:\n"
              "Actions, Members, ... Dynasty Central), any tab, then press F8.  (F9 aborts.)")
        keys.wait_mark()
    frame = stream.settle()[0]
    if screens.highlight_span(frame, cfg["hub"]["tab_box"]) is None:
        raise SystemExit("Couldn't find the selected tab in the tab bar. Is the hub showing?")
    screens.REFS.mkdir(exist_ok=True)
    frame.save(screens.ref_path("hub"))
    for old in screens.REFS.glob("hub_tab*.png"):      # from the old one-image-per-tab scheme
        old.unlink()
    cfg["hub"].pop("tabs", None)
    cfg["hub"].pop("wraps", None)
    screens.save_config(cfg)
    print("Hub taught (refs/hub.png).")


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
        print(f"  On the hub. Now navigate to {name} (controller or keyboard), then press F8.")
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
        elif back_key and back_key not in PS_NAMES:
            cfg["keymap"]["circle"] = back_key

    screen.update(route=route, hub_tab=tab, route_taught=True)
    screen.setdefault("verify_box", DEFAULT_VERIFY_BOX)
    screens.save_config(cfg)
    print(f"Saved route for '{name}' and its reference image refs/{name}.png.")
