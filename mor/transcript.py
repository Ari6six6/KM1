"""The transcript — the one shared channel the crew and operator speak in.

Every line is plain English, addressed to someone, appended to disk and echoed
to the terminal. A live turn reads only the recent *tail* (bounded, so one long
session doesn't blow up the prompt); the full record stays on disk.

Fenced code blocks are stripped on the way in: the transcript carries prose and
file references, not pasted code — that keeps lines readable and stops a pasted
log from poisoning every turn that reads it afterward.
"""

from __future__ import annotations

import json
import re
import time

from mor import ui

_FENCE = re.compile(r"```.*?```", re.DOTALL)
_MAX_LINE = 1500


def _plain(text: str) -> str:
    cleaned = _FENCE.sub("[code omitted — see the file]", text or "")
    return " ".join(cleaned.split()).strip()


def _cap(text: str) -> str:
    if len(text) <= _MAX_LINE:
        return text
    cut = text[:_MAX_LINE].rsplit(" ", 1)[0] or text[:_MAX_LINE]
    return cut + " …(trimmed)"


class Transcript:
    def __init__(self, path, *, echo: bool = True):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.echo = echo
        self._entries: list = []

    def post(self, speaker: str, addressee, text: str) -> dict:
        entry = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "speaker": speaker,
                 "addressee": addressee, "text": _cap(_plain(text))}
        self._entries.append(entry)
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        if self.echo:
            print(ui.line(speaker, addressee, entry["text"]))
        return entry

    def entries(self) -> list:
        return list(self._entries)

    def tail_text(self, n: int = 14) -> str:
        rows = self._entries[-n:]
        if not rows:
            return "(nothing said yet)"
        return "\n".join(
            e["speaker"] + (f"→{e['addressee']}" if e.get("addressee") else "")
            + f": {e['text']}" for e in rows)
