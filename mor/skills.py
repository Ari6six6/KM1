"""The shelf — the Third Evangelism, MoR-native.

A skill is a how-to note the realm learned the hard way and never wants to
learn twice: one markdown file each. The faces carry only the *index* — one
line per skill — in their context; the full body is pulled with `skill_load`
only when the moment needs it. The same frugality as the toolbox: everything
on the shelf is cheap, nothing is forced into a mind that doesn't need it.

Two shelves, mirroring the old harness: the **global** shelf (~/.mor/skills)
crosses every space; the **space's own** shelf (<space>/skills) overrides it
where they share a name. A face writes to its own space's shelf — what this
realm learned stays with this realm.
"""

from __future__ import annotations

import re
from pathlib import Path

from mor.config import mor_home

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_INDEX_LIMIT = 12  # how many one-liners the context carries


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name or ""))


def _global_dir() -> Path:
    return mor_home() / "skills"


def _space_dir(space) -> Path:
    return space.root / "skills"


def _shelf(space) -> dict:
    """name -> path, global first, the space's own winning name clashes."""
    shelf = {}
    for d in (_global_dir(), _space_dir(space)):
        if d.is_dir():
            for p in sorted(d.glob("*.md")):
                if valid_name(p.stem):
                    shelf[p.stem] = p
    return shelf


def _first_line(body: str) -> str:
    for ln in body.splitlines():
        ln = ln.strip().lstrip("#").strip()
        if ln:
            return ln[:80]
    return "(no description)"


def index(space, limit: int = _INDEX_LIMIT) -> str:
    """The one-line-per-skill digest the faces carry — names and first lines."""
    shelf = _shelf(space)
    if not shelf:
        return "the shelf is empty — no how-to notes yet"
    lines = [f"{name} — {_first_line(p.read_text('utf-8', 'replace'))}"
             for name, p in list(shelf.items())[:limit]]
    more = len(shelf) - len(lines)
    tail = f" (+{more} more on the shelf)" if more > 0 else ""
    return "; ".join(lines) + tail


def load(space, name: str):
    """The full body of one skill, or None if the shelf doesn't hold it."""
    p = _shelf(space).get((name or "").strip())
    if p is None:
        return None
    return p.read_text("utf-8", "replace")


def record(space, name: str, body: str):
    """Write a how-to onto the space's own shelf. Returns an error string, or
    None on success."""
    name = (name or "").strip()
    body = (body or "").strip()
    if not valid_name(name):
        return "a skill name is letters, digits, . _ - (start with a letter or digit)"
    if not body:
        return "a skill needs a body"
    d = _space_dir(space)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(body + "\n", "utf-8")
    return None
