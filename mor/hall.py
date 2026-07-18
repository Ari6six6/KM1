"""The Hall — the one public channel.

Every spoken word, plain English only, addressed to someone (except the
Master, whose word is caught automatically). Append-only to disk (the day's
record) and streamed live to the terminal. A live turn reads only the *tail*;
the full transcript lives at rest. Speaking code is forbidden — fenced code
blocks are stripped on the way in; agents may *reference* files, not paste them.
"""

from __future__ import annotations

import json
import re
import time

from mor import ui

_FENCE = re.compile(r"```.*?```", re.DOTALL)

# One line can never swamp the day. The Hall's tail rides every prompt a face
# sees, so a single wild line (a model loop, a pasted log) would otherwise
# poison every turn that follows it. A long line is cut; the full text was the
# model's, and the record notes the cut.
_MAX_LINE = 1500


def _plainen(text: str) -> str:
    """Strip fenced code — the Hall carries prose and references, never code."""
    cleaned = _FENCE.sub("[reference to code — see the file]", text or "")
    return " ".join(cleaned.split()).strip()


def _cap(text: str) -> str:
    if len(text) <= _MAX_LINE:
        return text
    cut = text[:_MAX_LINE].rsplit(" ", 1)[0] or text[:_MAX_LINE]
    return cut + " … (the line ran long — the Hall cut it)"


class Hall:
    def __init__(self, space, day: int, *, echo: bool = True):
        self.space = space
        self.day = day
        self.path = space.hall_path(day)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.echo = echo
        self._fold = None    # cached fold of the older Hall (see engine.compaction)
        self._fold_n = 0

    def post(self, speaker: str, addressee, text: str) -> dict:
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "speaker": speaker,
            "addressee": addressee,
            "text": _cap(_plainen(text)),
        }
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        if self.echo:
            print(ui.hall_line(speaker, addressee, entry["text"]))
        return entry

    def entries(self) -> list:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def tail(self, n: int = 12) -> list:
        return self.entries()[-n:]

    def tail_text(self, n: int = 12) -> str:
        return "\n".join(
            f"{e['speaker']}"
            + (f"→{e['addressee']}" if e.get("addressee") else "")
            + f": {e['text']}"
            for e in self.tail(n)
        )
