"""watch — a recurring order. The realm never sleeps.

A REPL answers when asked; a watch is standing work the daemon runs on a schedule
whether or not anyone is looking — "that repo's issues, every 6h, tell me what
changed." A watch is just an order with an interval: when it's due, the scheduler
runs it (no client attached) and it delivers an artifact like any other order.

Durable and plain: watches live in ``watches.json`` under the project. The daemon's
``WatchScheduler`` ticks them; ``run_due_watches`` is the pure core it calls, so
the firing logic tests without threads or a network.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import asdict, dataclass

from mor.config import load_json, save_json

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_interval(text: str) -> int:
    """'90s' → 90, '6h' → 21600, '1d' → 86400, '1h30m' → 5400, a bare number →
    seconds. Raises ValueError on anything that names no duration."""
    s = (text or "").strip().lower()
    if not s:
        raise ValueError("empty interval")
    if s.isdigit():
        n = int(s)
        if n <= 0:
            raise ValueError("interval must be positive")
        return n
    total, matched = 0, False
    for num, unit in re.findall(r"(\d+)\s*([smhd])", s):
        total += int(num) * _UNITS[unit]
        matched = True
    if not matched or total <= 0:
        raise ValueError(f"not a duration: {text!r} (try 90s, 30m, 6h, 1d)")
    return total


@dataclass
class Watch:
    id: str
    kind: str
    brief: str
    every: int
    last_run: float = 0.0
    created: str = ""

    def due(self, now: float) -> bool:
        return (now - self.last_run) >= self.every


class WatchStore:
    def __init__(self, project):
        self.path = project.root / "watches.json"

    def _load(self) -> dict:
        return load_json(self.path, {"watches": []})

    def list(self) -> list:
        return [Watch(**w) for w in self._load().get("watches", [])]

    def add(self, kind: str, brief: str, every: int) -> Watch:
        wid = time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex()
        w = Watch(id=wid, kind=kind, brief=brief, every=int(every), last_run=0.0,
                  created=time.strftime("%Y-%m-%d %H:%M:%S"))
        d = self._load()
        d["watches"].append(asdict(w))
        save_json(self.path, d)
        return w

    def remove(self, wid: str) -> bool:
        d = self._load()
        kept = [w for w in d["watches"] if w["id"] != wid]
        removed = len(kept) < len(d["watches"])
        d["watches"] = kept
        save_json(self.path, d)
        return removed

    def mark_run(self, wid: str, t: float) -> None:
        d = self._load()
        for w in d["watches"]:
            if w["id"] == wid:
                w["last_run"] = t
        save_json(self.path, d)


def run_due_watches(project, store: "WatchStore | None" = None, now: float | None = None,
                    *, client=None, echo: bool = False) -> list:
    """Run every watch that is due, as an order with no client attached. Returns the
    ids of the orders fired. The pure core the scheduler ticks."""
    from mor.order import run_order
    store = store or WatchStore(project)
    now = time.time() if now is None else now
    fired = []
    for w in store.list():
        if w.due(now):
            order = run_order(project, w.kind, w.brief, client=client, echo=echo)
            store.mark_run(w.id, now)
            fired.append(order.id)
    return fired


class WatchScheduler:
    """The daemon's clock — ticks the watches so the realm works the night shift."""

    def __init__(self, project, store: "WatchStore | None" = None, *,
                 interval: float = 30.0, on_event=None):
        self.project = project
        self.store = store or WatchStore(project)
        self.interval = float(interval)
        self.on_event = on_event or (lambda *_: None)
        self._stop = threading.Event()
        self._thread = None

    def tick(self) -> list:
        fired = run_due_watches(self.project, self.store)
        for oid in fired:
            self.on_event(f"watch fired → order {oid}")
        return fired

    def run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 — a bad watch never kills the scheduler
                pass

    def start(self) -> "WatchScheduler":
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
