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


class Streamer:
    """A live token line: the model's words as they arrive, on one rewritten line.

    This is the answer to 'a spinner where the agent's thoughts should be' — while
    a turn runs, the operator watches the text stream in, capped to a trailing
    window so it stays on one line and erases cleanly. TTY-only: on a pipe or in
    tests it does nothing and ``active`` stays False. ``feed`` is the on_token
    callback; ``clear`` wipes the line so a tool-observation log can print above
    it, and the next token re-renders."""

    def __init__(self, name: str, width: int = 72):
        self.name = name
        self.width = width
        self._buf = ""
        self.active = False

    def __enter__(self):
        if sys.stdout.isatty():
            self.active = True
            self._render()
        return self

    def feed(self, delta: str) -> None:
        if not self.active or not delta:
            return
        self._buf += delta
        self._render()

    def _render(self) -> None:
        tail = " ".join(self._buf.split())[-self.width:]
        sys.stdout.write("\r\033[2K  " + cyan(self.name) + dim(" ▍ ") + dim(tail))
        sys.stdout.flush()

    def clear(self) -> None:
        if self.active:
            sys.stdout.write("\r\033[2K")
            sys.stdout.flush()

    def __exit__(self, *a):
        self.clear()
        self.active = False


def line(speaker: str, addressee, text: str) -> str:
    paint = _colour_for(speaker)
    arrow = f" {dim('→')} {addressee}" if addressee else ""
    return f"{paint(speaker)}{arrow}{dim(':')} {text}"
