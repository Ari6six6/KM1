"""Paths, the project `space`, day counter, gate allowlist, and GPU state.

MoR keeps its home under $MOR_HOME (default ~/.mor). A *space* is one realm's
world on disk — its days, chants, walls, world-map, personas, and gate. The
`space` convention survives from Hermes: `space use <name>` / `space new <name>`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse


def mor_home() -> Path:
    return Path(os.environ.get("MOR_HOME", str(Path.home() / ".mor")))


def gpu_state_path() -> Path:
    return mor_home() / "gpu.json"


def current_space_file() -> Path:
    return mor_home() / "current_space"


def spaces_root() -> Path:
    return mor_home() / "spaces"


def current_space_name() -> str:
    f = current_space_file()
    if f.exists():
        name = f.read_text().strip()
        if name:
            return name
    return "realm"


def use_space(name: str) -> None:
    mor_home().mkdir(parents=True, exist_ok=True)
    current_space_file().write_text(name.strip() + "\n")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, data) -> None:
    """Write JSON atomically — a crash mid-write must never leave a torn
    gate/grimoire/world file behind (a half-written file would silently read
    back as the default, wiping the realm's memory)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


# A space name becomes directory names and container names — keep it plain and
# keep it inside MOR_HOME (no separators, no dots-led tricks like `..`).
_SPACE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def valid_space_name(name: str) -> bool:
    return bool(_SPACE_NAME.match(name or ""))


class Space:
    """One realm's world on disk."""

    def __init__(self, name: str):
        self.name = name
        self.root = spaces_root() / name

    # --- lifecycle -------------------------------------------------------
    def ensure(self) -> "Space":
        for sub in ("personas", "population", "chants", "days", "dreams"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        return self

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    def state(self) -> dict:
        return load_json(self.state_path, {"last_day": 0})

    def save_state(self, state: dict) -> None:
        save_json(self.state_path, state)

    def next_day_number(self) -> int:
        st = self.state()
        return int(st.get("last_day", 0)) + 1

    def commit_day(self, n: int) -> None:
        st = self.state()
        st["last_day"] = int(n)
        self.save_state(st)

    # --- artifacts -------------------------------------------------------
    def hall_path(self, day: int) -> Path:
        return self.root / "days" / f"day-{day:04d}" / "hall.jsonl"

    def chant_path(self, day: int) -> Path:
        return self.root / "chants" / f"day-{day:04d}.md"

    def dream_path(self, day: int) -> Path:
        # The Thirteenth: what the realm dreamed the night day N ended — the
        # structured record, seeded into the next dawn's grimoire and read into
        # the Cathedral. Keyed by the day that ended, posted at the day that opens.
        return self.root / "dreams" / f"day-{day:04d}.json"

    def persona_path(self, role: str) -> Path:
        return self.root / "personas" / f"{role}.md"

    def inside_wall_path(self, role: str) -> Path:
        return self.root / "population" / role / "inside_wall.md"

    def outside_wall_path(self, role: str) -> Path:
        return self.root / "population" / role / "outside_wall.md"

    def world_path(self) -> Path:
        return self.root / "world.json"

    def grimoire_path(self) -> Path:
        return self.root / "grimoire.json"

    def gate_path(self) -> Path:
        return self.root / "gate.json"

    # --- gate (egress allowlist) ----------------------------------------
    # The gate is the always-lit safety rail (the Eighth Evangelism, the taint
    # boundary): the Warrior crosses only to a domain the Master has authorized.
    # `authorize *` opens it wide in one word — full power, zero friction — for a
    # Master who wants nothing between him and the world.
    def allowlist(self) -> list:
        return load_json(self.gate_path(), {"domains": []}).get("domains", [])

    def egress_allowed(self, domain: str) -> bool:
        al = self.allowlist()
        return "*" in al or domain in al

    # A plausible public hostname: dot-separated labels of letters, digits, and
    # hyphens (no label starting or ending with one). Anything else is not a
    # place the gate can open.
    _HOSTNAME = re.compile(
        r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)*[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

    @classmethod
    def normalize_domain(cls, domain: str) -> str:
        """The gate matches on URL hostnames, so what the Master types must be
        stored as one: lowercase, no scheme, no path, no port. `authorize
        https://Example.com/a` opens `example.com` — stored raw it would open
        nothing, silently. Returns '' for input that names no host."""
        d = (domain or "").strip().lower()
        if not d or d == "*":
            return d
        if "://" not in d:
            d = "//" + d
        host = (urlparse(d).hostname or "").rstrip(".")
        return host if cls._HOSTNAME.match(host) else ""

    def authorize(self, domain: str) -> str:
        """Open the gate for a domain. Returns the normalized domain actually
        stored ('' if the input named no host — the gate stays shut)."""
        domain = self.normalize_domain(domain)
        if not domain:
            return ""
        data = load_json(self.gate_path(), {"domains": []})
        domains = data.setdefault("domains", [])
        if domain not in domains:
            domains.append(domain)
        save_json(self.gate_path(), data)
        return domain


def load_space() -> Space:
    return Space(current_space_name()).ensure()
