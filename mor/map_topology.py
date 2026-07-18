"""The topological radar — where in a codebase to look first, by weight not whim.

A pure-regex scan of a Python tree: it reads the `import` lines, counts how many
local modules lean on each one (in-degree) and how many each one leans on
(out-degree), and ranks the tree by pull. The most-imported module is the one
whose change ripples furthest — so a face reads it before it reads anything else.

No parser, no dependency: `import x` / `from x import y` is a line-level pattern,
and centrality is just tallying the edges. A cheap map of the ground, drawn before
the first step. (This is orientation, not belief — the grimoire holds what the
realm concludes; this only says where to point the lantern.)
"""

from __future__ import annotations

import re
from pathlib import Path

_IMPORT = re.compile(r"^\s*(?:from\s+([.\w]+)\s+import\b|import\s+([.\w]+))")


def _imports_in(text: str) -> set:
    """The top-level module names a file imports (dotted paths cut to their head)."""
    out = set()
    for line in text.splitlines():
        m = _IMPORT.match(line)
        if not m:
            continue
        name = (m.group(1) or m.group(2) or "").lstrip(".")
        if name:
            out.add(name.split(".")[0])
    return out


def scan(root) -> dict:
    """Map a Python tree to its local import edges. Returns {module: {in, out}}
    counting only edges between modules that actually live in the tree."""
    root = Path(root)
    files = [p for p in root.rglob("*.py") if p.is_file()]
    local = {p.stem for p in files}
    deg = {stem: {"in": 0, "out": 0} for stem in local}
    for p in files:
        try:
            imports = _imports_in(p.read_text("utf-8", "replace"))
        except OSError:
            continue
        for target in imports & local:
            if target == p.stem:
                continue  # a module importing itself is noise, not an edge
            deg[p.stem]["out"] += 1
            deg[target]["in"] += 1
    return deg


def summary(root, limit: int = 8) -> str:
    """The tree ranked by pull — most-imported first — as a plain line a face
    reads to choose where to look before it reads a single file."""
    deg = scan(root)
    if not deg:
        return "no Python modules found to map"
    ranked = sorted(deg.items(), key=lambda kv: (kv[1]["in"], kv[1]["out"]), reverse=True)
    bits = [f"{name} (imported by {d['in']}, imports {d['out']})"
            for name, d in ranked[:limit]]
    return "topology, most load-bearing first: " + "; ".join(bits)
