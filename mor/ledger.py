"""The realm ledger — one append-only event stream for the night shift.

The Master's homogenization key: complex state becomes events in one stream, and
the application reads projections of it. Orders and the Field keep their own logs
(their own little ledgers); this is the realm-wide stream the *night* writes to —
benchmark scores, forge verdicts, dream questions — and the morning report reads
back. Plain JSONL under ``realm/events.jsonl``; nothing here is a live variable a
crash can lose.
"""

from __future__ import annotations

import json
import time


def events_path(project):
    return project.root / "realm" / "events.jsonl"


def record(project, kind: str, **payload) -> dict:
    path = events_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _count(path)
    event = {"seq": existing, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
             "t": time.time(), "kind": kind, **payload}
    with path.open("a") as f:
        f.write(json.dumps(event) + "\n")
    return event


def events(project, kind: str | None = None) -> list:
    path = events_path(project)
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if kind is None or e.get("kind") == kind:
            out.append(e)
    return out


def _count(path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text().splitlines() if line.strip())
