"""The tunnel supervisor — the tunnel heals itself, no human input.

A rented box is only useful while the SSH tunnel to it is up. The old story was
manual: the tunnel drops, ``mor gpu status`` shows it down, the operator notices
and types ``mor gpu reconnect``. That is not a night shift. The supervisor watches
the tunnel and re-dials it — with backoff — the moment it dies, so an unattended
realm keeps its oracle whether or not anyone is looking.

It is dependency-injected: given an ``is_alive`` probe and a ``redial`` action it
knows nothing about ssh, which is why it tests without a network. ``gpucmd`` binds
it to the real PID-tracked tunnel (``mor gpu watch``).
"""

from __future__ import annotations

import threading


class TunnelSupervisor:
    def __init__(self, is_alive, redial, *, check_interval: float = 5.0,
                 backoff=(2, 5, 10, 20, 30), on_event=None):
        self.is_alive = is_alive
        self.redial = redial
        self.check_interval = float(check_interval)
        self.backoff = tuple(backoff) or (5,)
        self.on_event = on_event or (lambda *_: None)
        self.consecutive_failures = 0
        self.redials = 0
        self._stop = threading.Event()
        self._thread = None

    def next_backoff(self) -> float:
        """How long to wait before the next re-dial, growing with the failure run
        and capped at the last step."""
        idx = min(max(self.consecutive_failures - 1, 0), len(self.backoff) - 1)
        return self.backoff[idx]

    def tick(self) -> str:
        """One supervision step, without sleeping. Returns 'up' (nothing to do),
        'redialed' (was down, restored it), or 'down' (still down, will retry)."""
        if self.is_alive():
            self.consecutive_failures = 0
            return "up"
        self.consecutive_failures += 1
        self.on_event(f"tunnel down — redialing (attempt {self.consecutive_failures})")
        if self.redial():
            self.redials += 1
            self.consecutive_failures = 0
            self.on_event("tunnel restored")
            return "redialed"
        return "down"

    def run(self) -> None:
        """Loop until stopped: check, then wait ``check_interval`` when up or the
        next backoff when still down. For a background thread or ``nohup``."""
        delay = 0.0
        while not self._stop.wait(delay):
            result = self.tick()
            delay = self.check_interval if result in ("up", "redialed") else self.next_backoff()

    def start(self) -> "TunnelSupervisor":
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
