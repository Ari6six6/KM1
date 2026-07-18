"""The Tenth Evangelism — the Forge: the realm's own code, within reach.

Until now every write tool was jailed to the workspace, and the engine that
thinks, the tools that act, and the prompts that speak were outside the walls —
readable by no face, writable by none. A realm that cannot touch its own
machinery can learn, but it cannot *improve*.

This module opens the source tree as a second, guarded scope. It is given to
exactly one face — the Smith, who works only at night, inside `improve` — and
it is guarded the way the gate is guarded: enforced here, not asked for.

The guards:
  - confined to the repository root (the directory holding pyproject.toml) —
    nothing outside it, ever;
  - only text source files may be written (.py .md .txt .json .toml .cfg) —
    no binaries, no hidden paths, no deletes (deletion is a revert's job, and
    reverts belong to git, not to a face);
  - every write is whole-file and logged, so `git diff` after the cycle shows
    the Master exactly what the Smith changed — no silent edits;
  - the day-faces (Wizard, General, Warrior) never receive these tools. The
    Smith does not walk in the Hall; he works in the Forge and reports.

Safety above the rails: the taint boundary and the egress chokepoint live in
code the Smith *can* read — and the test suite (test_hardening) proves them
after every mutation. A change that weakens the rails turns the suite red,
and a red suite is an automatic revert. The rails guard themselves.
"""

from __future__ import annotations

import re
from pathlib import Path

_WRITE_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".cfg"}
_READ_WINDOW = 8000
_MAX_BYTES = 2_000_000


def source_root() -> Path:
    """The repository root — the parent of the mor package, where pyproject
    lives. Resolved once, so a face can never argue it into somewhere else."""
    return Path(__file__).resolve().parent.parent


def _safe(rel: str) -> Path:
    root = source_root()
    p = (root / (rel or ".")).resolve()
    if p != root and root not in p.parents:
        raise ValueError("path escapes the source tree")
    return p


def _check_writable(p: Path) -> str:
    if p.suffix.lower() not in _WRITE_SUFFIXES:
        return (f"the Forge writes source text only "
                f"({', '.join(sorted(_WRITE_SUFFIXES))}) — not '{p.suffix or p.name}'")
    if any(part.startswith(".") and part not in (".",) for part in p.parts):
        return "the Forge never touches hidden paths"
    return ""


def read(rel: str, offset: int = 0) -> str:
    p = _safe(rel)
    if not p.exists():
        return f"ERROR: no such file: {rel}"
    if p.is_dir():
        return f"ERROR: {rel} is a directory — use source_list"
    if p.stat().st_size > _MAX_BYTES:
        return f"ERROR: {rel} is too large to read whole — page it with offset"
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    text = p.read_text("utf-8", "replace")
    chunk = text[offset:offset + _READ_WINDOW]
    remaining = len(text) - (offset + len(chunk))
    if remaining > 0:
        chunk += (f"\n\n[TRUNCATED: {remaining:,} characters remain. Call "
                  f"source_read with offset={offset + _READ_WINDOW} to continue.]")
    return chunk


def write(rel: str, content: str) -> str:
    """Whole-file write (create or overwrite). Returns an error string prefixed
    ERROR, or a one-line receipt naming the file and its size."""
    try:
        p = _safe(rel)
    except ValueError as e:
        return f"ERROR: {e}"
    err = _check_writable(p)
    if err:
        return f"ERROR: {err}"
    if not (content or "").strip():
        return "ERROR: refusing to write an empty file"
    existed = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, "utf-8")
    verb = "rewrote" if existed else "forged"
    return f"{verb} {p.relative_to(source_root())} ({len(content):,} chars)"


def list_dir(rel: str = ".") -> str:
    p = _safe(rel)
    if not p.is_dir():
        return f"ERROR: no such directory: {rel}"
    out = []
    for child in sorted(p.iterdir()):
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        mark = "/" if child.is_dir() else ""
        out.append(f"{child.name}{mark}")
    return "\n".join(out) or "(empty)"


def search(pattern: str, rel: str = ".") -> str:
    """Regex search over the source tree (text files only). Returns matching
    lines as path:line — capped, so a broad pattern can't flood the turn."""
    try:
        rx = re.compile(pattern or "")
    except re.error as e:
        return f"ERROR: bad regex: {e}"
    base = _safe(rel)
    files = [base] if base.is_file() else sorted(
        f for f in base.rglob("*") if f.is_file()
        and f.suffix.lower() in _WRITE_SUFFIXES
        and "__pycache__" not in f.parts and not f.name.startswith("."))
    hits = []
    for f in files:
        try:
            for i, line in enumerate(f.read_text("utf-8", "replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f.relative_to(source_root())}:{i}: {line.strip()[:140]}")
        except OSError:
            continue
        if len(hits) >= 60:
            return "\n".join(hits) + f"\n[TRUNCATED at 60 hits — narrow the pattern]"
    return "\n".join(hits) or "no matches"
