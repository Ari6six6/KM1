"""The territory — what a colony leaves behind when it is razed.

A colony is sacrificial; its record is not. When a colony is planted the
territory opens a book; when it is razed the ground is read and the book is
closed — but never burned. The record (<space>/territories/<name>.json) is
structured data, kept so it can be accessed and operated on at any later
stage: when the colony was planted and razed, every operation run there and
its result, and the file tree with sizes and digests of the text it held.

These are the realm's known modules — the ground outlives the boots.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from mor.config import load_json, save_json

_SLUG = re.compile(r"[^a-z0-9._-]+")
_TEXT_DIGEST_CAP = 4000       # chars of a file's digest kept in the record
_DIGEST_MAX_BYTES = 1_000_000  # bigger files are listed, not digested
_MAX_FILES = 200              # tree entries kept per territory


def slug(name: str) -> str:
    return _SLUG.sub("-", (name or "").strip().lower()).strip("-") or "unnamed"


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def record_path(space, name: str) -> Path:
    return space.root / "territories" / f"{slug(name)}.json"


def colony_dir(space, name: str) -> Path:
    return space.root / "colonies" / slug(name)


def begin(space, name: str) -> dict:
    """Open a territory's book when the colony is planted."""
    rec = load_json(record_path(space, name), {})
    rec.update({
        "name": slug(name),
        "space": space.name,
        "colonized": rec.get("colonized") or _today(),
        "standing": True,
        "razed": None,
    })
    save_json(record_path(space, name), rec)
    return rec


def _read_ops(cdir: Path) -> list:
    ops = []
    ops_file = cdir / "ops.jsonl"
    if ops_file.exists():
        for ln in ops_file.read_text("utf-8", "replace").splitlines():
            try:
                ops.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return ops


def _read_tree(cdir: Path) -> list:
    files = []
    for p in sorted(cdir.rglob("*")):
        if not p.is_file() or p.name == "ops.jsonl":
            continue
        if len(files) >= _MAX_FILES:
            break
        try:
            size = p.stat().st_size
        except OSError:
            continue
        entry = {"path": str(p.relative_to(cdir)), "bytes": size}
        if size <= _DIGEST_MAX_BYTES:
            head = p.read_bytes()[:2048]
            if b"\0" not in head:  # text ground only
                entry["digest"] = p.read_text("utf-8", "replace")[:_TEXT_DIGEST_CAP]
        files.append(entry)
    return files


def harvest(space, name: str) -> dict:
    """Close the book at raze: fold the colony's ground into the record. The
    colony dir itself is left standing — the record points at it."""
    cdir = colony_dir(space, name)
    rec = load_json(record_path(space, name), {})
    rec.update({
        "name": slug(name),
        "space": space.name,
        "colonized": rec.get("colonized") or _today(),
        "standing": False,
        "razed": _today(),
    })
    if cdir.is_dir():
        rec["ops"] = _read_ops(cdir)
        rec["files"] = _read_tree(cdir)
        rec["counts"] = {
            "files": len(rec["files"]),
            "bytes": sum(f["bytes"] for f in rec["files"]),
            "ops": len(rec["ops"]),
        }
    save_json(record_path(space, name), rec)
    return rec


def load(space, name: str) -> dict:
    return load_json(record_path(space, name), {})


def all(space) -> list:
    d = space.root / "territories"
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def summary(space, name: str) -> str:
    """A plain-text reading of one territory — for the Master, and for recall."""
    rec = load(space, name)
    if not rec:
        return f"no territory '{slug(name)}' is known"
    counts = rec.get("counts", {})
    lines = [
        f"territory {rec['name']} — planted {rec.get('colonized', '?')}, "
        + (f"standing" if rec.get("standing") else f"razed {rec.get('razed', '?')}"),
        f"  ground: {counts.get('files', 0)} files, {counts.get('bytes', 0):,} bytes; "
        f"{counts.get('ops', 0)} operations on record",
    ]
    for op in rec.get("ops", [])[-5:]:
        lines.append(f"  $ {op.get('cmd', '')}  → rc {op.get('rc', '?')}")
    for f in rec.get("files", [])[:10]:
        lines.append(f"  {f['path']} ({f['bytes']:,} B)")
    return "\n".join(lines)
