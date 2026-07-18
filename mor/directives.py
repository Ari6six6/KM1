"""Standing directives — the First Evangelism, MoR-native.

The Master's standing word: rules that hold for every turn until lifted —
"never use curl", "always show the numbers", "the Warrior asks before any
sortie past midnight". They persist in the space, they ride every face's
context (one line, in the volatile turn), and they are plain text — the realm
doesn't interpret them, it OBEYS them, because every face reads them every
turn it takes.

Reconciliation, kept honest: a new directive that closely resembles an old one
is reported as a possible overlap — the Master is sovereign and decides; the
realm never silently stacks near-duplicates and calls it understanding.
"""

from __future__ import annotations

import re
import time

from mor.config import load_json, save_json

_OVERLAP = 0.6  # token-Jaccard at which a new directive is flagged as resembling an old


def _path(space):
    return space.root / "directives.json"


def all(space) -> list:
    return load_json(_path(space), {"directives": []}).get("directives", [])


def _save(space, directives) -> None:
    save_json(_path(space), {"directives": directives})


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", _norm(text)))


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def add(space, text: str):
    """Set a standing directive. Returns (index, warning) — warning names an
    existing directive it resembles (a possible contradiction to reconcile), or
    None. An exact duplicate is refused: the word already stands."""
    text = " ".join((text or "").split())
    directives = all(space)
    for i, d in enumerate(directives, 1):
        if _norm(d.get("text", "")) == _norm(text):
            return i, "that word already stands as directive %d" % i
    warning = None
    new_tokens = _tokens(text)
    for i, d in enumerate(directives, 1):
        if _jaccard(new_tokens, _tokens(d.get("text", ""))) >= _OVERLAP:
            warning = ("it closely resembles directive %d ('%s') — reconcile, or "
                       "let both stand" % (i, d.get("text", "")))
            break
    directives.append({"text": text, "set": time.strftime("%Y-%m-%d")})
    _save(space, directives)
    return len(directives), warning


def drop(space, index: int):
    """Lift a standing directive by its 1-based number. True if one was lifted."""
    directives = all(space)
    if not 1 <= index <= len(directives):
        return False
    directives.pop(index - 1)
    _save(space, directives)
    return True


def summary(space) -> str:
    """The one-line-per-rule digest the faces carry — '' when no word stands."""
    directives = all(space)
    if not directives:
        return ""
    return "; ".join(f"{i}. {d['text']}" for i, d in enumerate(directives, 1))
