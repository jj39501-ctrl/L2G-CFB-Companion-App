"""python -m capture <command>

  check [--fix]            Check the chiaki-ng window and print the picture geometry.
  teach hub                Record the Dynasty hub's tabs (do this first).
  teach <screen>           Record the route from the hub to a screen.
  here <screen>            Capture the screen that's showing now, using its settings.
  run [screen ...]         Visit each taught screen (default: all) and capture it.
  list                     Show the configured screens and whether they're taught.
"""

import argparse
import json
import sys
import time
from datetime import datetime

from . import display, screens, teach
from .stream import Stream


def open_stream(cfg, fix):
    disp, problems, notes = display.preflight(cfg["window_title"], fix=fix)
    for n in notes:
        print("  " + n)
    if problems:
        for p in problems:
            print("  PROBLEM: " + p)
        sys.exit(1)
    return Stream(disp, cfg["keymap"])


def write_manifest(run_dir, stream, results):
    d = stream.display
    manifest = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "picture": {"width": d.video.width, "height": d.video.height},
        "screens": {name: [str(p.relative_to(run_dir)).replace("\\", "/") for p in files]
                    for name, files in results.items()},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(prog="python -m capture")
    ap.add_argument("command", choices=["check", "teach", "here", "run", "list"])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--fix", action="store_true",
                    help="restore/maximize the chiaki-ng window if it's minimized or too small")
    args = ap.parse_args()
    cfg = screens.load_config()

    if args.command == "list":
        for name, s in cfg["screens"].items():
            state = "taught" if s.get("route_taught") else "not taught"
            print(f"  {name:18} {s.get('mode', 'single'):7} {state}")
        return

    stream = open_stream(cfg, args.fix)
    if args.command == "check":
        print("Ready to capture.")
        return

    if args.command == "teach":
        if len(args.names) != 1:
            sys.exit("Usage: python -m capture teach hub | <screen>")
        if args.names[0] == "hub":
            teach.teach_hub(stream, cfg)
        else:
            teach.teach_screen(stream, cfg, args.names[0])
        return

    run_dir = screens.ROOT / "captures" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    if args.command == "here":
        if len(args.names) != 1:
            sys.exit("Usage: python -m capture here <screen>")
        name = args.names[0]
        files = screens.capture_here(stream, cfg["screens"][name], run_dir / name)
        write_manifest(run_dir, stream, {name: files})
        print(f"Saved {len(files)} frames to {run_dir}")
        return

    # run
    names = args.names or [n for n, s in cfg["screens"].items() if s.get("route_taught")]
    nav = screens.Navigator(stream, cfg)
    results, failed = {}, []
    for name in names:
        t0 = time.time()
        print(f"{name}:", flush=True)
        try:
            nav.goto(name)
            results[name] = screens.capture_here(stream, cfg["screens"][name], run_dir / name)
            print(f"  {len(results[name])} frames in {time.time() - t0:.0f}s", flush=True)
        except RuntimeError as e:
            print(f"  SKIPPED: {e}", flush=True)
            failed.append(name)
    write_manifest(run_dir, stream, results)
    print(f"Done. {sum(map(len, results.values()))} frames in {run_dir}"
          + (f"; skipped {', '.join(failed)}" if failed else ""))


if __name__ == "__main__":
    main()
