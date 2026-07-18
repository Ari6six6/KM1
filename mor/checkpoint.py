"""The Sixth Evangelism — checkpointing, kept lit by the covenant of safety.

Before the realm changes its own record (dawn and dusk are the great rewriting
moments), it snapshots the space — a plain copy, not git, so any machine is
covered. `checkpoint restore <id>` rewinds the space to just before things went
sideways. Snapshots live OUTSIDE the space (~/.mor/checkpoints/<space>/), so a
restore can never eat its own history, and only the last several are kept.

It is pure safety and costs a directory copy, so it asks no permission.
"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from mor.config import mor_home

_KEEP = 10          # how many snapshots per space survive the pruning
_SKIP_BYTES = 16_000_000  # a file bigger than this is noted, not copied
# id = date-second + a per-space sequence + label — strictly name-sortable, so
# "oldest first" never depends on filesystem timestamp granularity.
_NAME = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9]{6}(-[A-Za-z0-9._-]+)?$")
_SEQ = re.compile(r"^[0-9]{8}-[0-9]{6}-([0-9]{6})")


def _root(space) -> Path:
    return mor_home() / "checkpoints" / space.name


def _slug(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", (label or "").strip()).strip("-")[:40]


def _next_id(space, label: str) -> str:
    root = _root(space)
    ts = time.strftime("%Y%m%d-%H%M%S")
    seq = 1
    if root.is_dir():
        seq += max([int(m.group(1)) for p in root.iterdir()
                    if (m := _SEQ.match(p.name))] or [0])
    slug = f"-{_slug(label)}" if _slug(label) else ""
    while True:
        sid = f"{ts}-{seq:06d}{slug}"
        if not (root / sid).exists():
            return sid
        seq += 1


def snapshot(space, label: str = "manual") -> str:
    """Copy the space aside. Returns the snapshot id ('' if it couldn't run —
    safety never breaks the realm it guards)."""
    try:
        dest = _root(space) / _next_id(space, label)
        skipped = []

        def ignore(dirpath, names):
            out = []
            for n in names:
                p = Path(dirpath) / n
                try:
                    if p.is_file() and p.stat().st_size > _SKIP_BYTES:
                        skipped.append(n)
                        out.append(n)
                except OSError:
                    continue
            return out

        shutil.copytree(space.root, dest, ignore=ignore)
        if skipped:
            (dest / "SKIPPED.txt").write_text(
                "files over the size line, not copied:\n" + "\n".join(skipped) + "\n")
        _prune(space)
        return dest.name
    except Exception:  # noqa: BLE001 — never let the safety rail kill the day
        return ""


def _snapshots(space) -> list:
    """Snapshot dirs, oldest first — the id's sequence makes name order == the
    order they landed in, always."""
    root = _root(space)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and _NAME.match(p.name))


def _prune(space) -> None:
    snaps = _snapshots(space)
    for old in snaps[:max(0, len(snaps) - _KEEP)]:
        shutil.rmtree(old, ignore_errors=True)


def list_snapshots(space) -> list:
    return [p.name for p in _snapshots(space)]


def restore(space, snapshot_id: str):
    """Rewind the space to a snapshot. A fresh 'pre-restore' snapshot is taken
    first — the rail never burns the present to save the past. Returns (ok,
    message)."""
    sid = (snapshot_id or "").strip()
    if not _NAME.match(sid):
        return False, f"'{sid}' is not a snapshot id — see `checkpoint` for the list"
    src = _root(space) / sid
    if not src.is_dir():
        return False, f"no snapshot {sid} — see `checkpoint` for the list"
    snapshot(space, "pre-restore")
    tmp = space.root.with_name(space.root.name + ".restore-tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp)          # stage the past beside the present...
    shutil.rmtree(space.root)
    tmp.rename(space.root)             # ...then swap — no half-restored space
    return True, f"the space stands as it did at {sid}"
