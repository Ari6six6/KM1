"""Folding the Hall — the bounded window, cut from Hermes's compaction.

The Master's own law: a live turn sees the tail; the full record lives at rest.
The whole Hall is always on disk (`days/day-NNNN/hall.jsonl`). But a face that's
about to speak shouldn't carry a whole long day verbatim — so once the Hall grows
past a trigger, the older middle is folded into a short summary (who decided what,
what the Warrior found, open threads) while the recent lines stay word-for-word.

The fold is cached on the Hall and only recomputed as the folded region grows, so
a long day doesn't spend a model call on every single beat. Served → the oracle
folds; offline → a plain marker (the record is still on disk either way).
"""

from __future__ import annotations

from mor.engine.backend import MockBackend

TRIGGER_ENTRIES = 40      # fold once the Hall passes this many lines
KEEP_LAST = 12            # recent lines always kept verbatim
REFOLD_EVERY = 20         # only re-summarize after this many more lines land

_FOLD_PROMPT = (
    "Summarize this Hall transcript compactly for a participant who needs the gist "
    "of what has happened so far. Preserve: who decided what, what the Warrior found "
    "outside, any strategy set, and any open threads. Plain English, a few sentences, "
    "no preamble.\n\nHALL:\n{slice}"
)


def render(entries: list) -> str:
    return "\n".join(
        e["speaker"] + (f"→{e['addressee']}" if e.get("addressee") else "")
        + f": {e['text']}"
        for e in entries) or "(quiet)"


def _fold(older: list, backend) -> str:
    if isinstance(backend, MockBackend) or not older:
        return f"({len(older)} earlier lines folded away — the full day is on the record)"
    res = backend.chat([{"role": "user",
                         "content": _FOLD_PROMPT.format(slice=render(older))}])
    text = (res.content or "").strip()
    return text or f"({len(older)} earlier lines folded away — full record on disk)"


def hall_view(hall, backend, *, keep_last: int = KEEP_LAST,
              trigger: int = TRIGGER_ENTRIES) -> str:
    """The bounded view of the Hall a face carries into its turn."""
    entries = hall.entries()
    if len(entries) <= trigger:
        return render(entries[-keep_last:]) if entries else "(quiet)"
    older, recent = entries[:-keep_last], entries[-keep_last:]
    n = len(older)
    if getattr(hall, "_fold", None) is None or n - getattr(hall, "_fold_n", 0) >= REFOLD_EVERY:
        hall._fold = _fold(older, backend)
        hall._fold_n = n
    return ("EARLIER IN THE HALL (folded — full record on disk):\n" + hall._fold
            + "\n\nRECENT (verbatim):\n" + render(recent))
