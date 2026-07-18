"""Tiny terminal helpers — colour, and a transcript line rendered on screen.

No dependencies; ANSI only, and silently disabled when stdout isn't a tty or
NO_COLOR is set.
"""

from __future__ import annotations

import os
import sys

_ENABLED = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

_PALETTE = ("36", "33", "32", "35", "34", "91", "95")  # for speakers, cycled


def _c(code: str):
    def paint(text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if _ENABLED else text
    return paint


dim = _c("2")
bold = _c("1")
red = _c("31")
green = _c("32")
yellow = _c("33")
blue = _c("34")
magenta = _c("35")
cyan = _c("36")
grey = _c("90")


def _colour_for(name: str):
    if name == "operator":
        return magenta
    if name in ("system", None):
        return grey
    idx = sum(ord(ch) for ch in name) % len(_PALETTE)
    return _c(_PALETTE[idx])


def bar(fraction: float, width: int = 22, label: str = "") -> str:
    """A dependency-free progress bar: [█████·········]  45%  label."""
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    body = "█" * filled + "·" * (width - filled)
    tail = f"  {label}" if label else ""
    return f"[{body}] {int(fraction * 100):3d}%{tail}"


class Spinner:
    """A live 'is thinking…' ticker for the long, silent model calls.

    A daemon thread rewrites one line — ``⠋ lead is thinking… 8.4s`` — so a slow
    turn never looks frozen. TTY-only: on a pipe or in tests it does nothing and
    ``active`` stays False, so callers can fall back to plain logging. ``set()``
    updates the label mid-turn (e.g. to the tool currently running)."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label: str = "working"):
        self.label = label
        self.active = False
        self._stop = None
        self._thread = None
        self._t0 = None

    def set(self, label: str) -> None:
        self.label = label

    def __enter__(self):
        import sys
        import threading
        import time
        if sys.stdout.isatty():
            self.active = True
            self._stop = threading.Event()
            self._t0 = time.time()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def _run(self):
        import sys
        import time
        i = 0
        while not self._stop.wait(0.1):
            i += 1
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write("\r  " + cyan(frame) + " "
                             + dim(f"{self.label}… {time.time() - self._t0:.1f}s") + "   ")
            sys.stdout.flush()

    def __exit__(self, *a):
        import sys
        self.active = False
        if self._stop:
            self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.3)
        if sys.stdout.isatty():
            sys.stdout.write("\r" + " " * 80 + "\r")
            sys.stdout.flush()


def line(speaker: str, addressee, text: str) -> str:
    paint = _colour_for(speaker)
    arrow = f" {dim('→')} {addressee}" if addressee else ""
    return f"{paint(speaker)}{arrow}{dim(':')} {text}"
