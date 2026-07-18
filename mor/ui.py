"""Tiny terminal helpers — colour, and the Hall's voices rendered on screen.

No dependencies; ANSI only, and silently disabled when stdout isn't a tty or
NO_COLOR is set.
"""

from __future__ import annotations

import os
import sys

_ENABLED = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str):
    def paint(text: str) -> str:
        if not _ENABLED:
            return text
        return f"\033[{code}m{text}\033[0m"
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

# The Hall's voices — each speaker a colour so the eye can follow a conversation.
VOICE = {
    "master": magenta,
    "wizard": cyan,
    "general": yellow,
    "warrior": red,
    "chant": green,
    "system": grey,
}

GLYPH = {
    "master": "♔ Master",
    "wizard": "✷ Wizard",
    "general": "✦ General",
    "warrior": "⚔ Warrior",
    "chant": "♪ Chant",
    "system": "·",
}


def bar(fraction: float, width: int = 22, label: str = "") -> str:
    """A dependency-free progress bar: [█████·········]  45%  label."""
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    body = "█" * filled + "·" * (width - filled)
    tail = f"  {label}" if label else ""
    return f"[{body}] {int(fraction * 100):3d}%{tail}"


def hall_line(speaker: str, addressee: str | None, text: str) -> str:
    paint = VOICE.get(speaker, grey)
    who = GLYPH.get(speaker, speaker)
    arrow = f" {dim('→')} {GLYPH.get(addressee, addressee)}" if addressee else ""
    return f"{paint(who)}{arrow}{dim(':')} {text}"
