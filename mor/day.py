"""light and dark — the day, the Chant, and the walls.

The scripture's memory ritual, kept as the debate settled it: **projections, not a
database.** The realm works a day; at **dark** the day's Hall is folded into one
small thing that crosses the night — the **Chant** (the realm's memory of who it
was that day) — and each face rewrites its two **walls** (inside: who I am; outside:
what I make of the others). At **light** the Chant is posted and each face wakes to
*persona + walls + last Chant*, a blank slate but for what the ritual kept.

Everything here is a **deterministic projection of the recorded Hall** — the same
day's entries always fold to the same Chant and walls, byte for byte. A served
model may later *voice* the Chant richer (the Wizard's song); the ground is always
the projection, never invention. Identity rides the ritual; facts ride retrieval
(``memory.py``). Both, each doing the job the other can't.
"""

from __future__ import annotations

import json
import time

from mor.config import load_json, save_json


def _realm_dir(project):
    return project.root / "realm"


def day_number(project) -> int:
    """The number of the last closed day (0 = none yet)."""
    return int(load_json(_realm_dir(project) / "day.json", {"day": 0}).get("day", 0))


def _speakers(entries: list) -> list:
    seen = []
    for e in entries:
        s = e.get("speaker")
        if s and s != "operator" and s not in seen:
            seen.append(s)
    return seen


def _first_sentence(text: str, limit: int = 140) -> str:
    t = " ".join((text or "").split())
    for sep in (". ", "! ", "? "):
        i = t.find(sep)
        if 0 < i < limit:
            return t[:i + 1]
    return t[:limit]


def compose_chant(entries: list, day_n: int) -> str:
    """The day's Hall → a short chant (≤200 words), deterministic. Names the day and
    keeps one distilled line per voice — the realm's memory of who it was."""
    speakers = _speakers(entries)
    lines = [f"Day {day_n}."]
    if not speakers:
        lines.append("The hall was quiet; nothing crossed the day.")
    else:
        lines.append("The hall heard " + ", ".join(speakers) + ".")
        for s in speakers:
            last = ""
            for e in entries:
                if e.get("speaker") == s and e.get("text"):
                    last = e["text"]
            if last:
                lines.append(f"{s} — {_first_sentence(last)}")
    chant = "\n".join(lines)
    words = chant.split()
    if len(words) > 200:
        chant = " ".join(words[:200]) + " …"
    return chant


def compose_walls(entries: list, names: list) -> dict:
    """Each face's two walls, deterministic from the day's Hall. Inside: a self-image
    from what it said; outside: what each other face said to it — relations earned,
    not fixed."""
    walls = {}
    for name in names:
        mine = [e for e in entries if e.get("speaker") == name and e.get("text")]
        inside = (f"I spoke {len(mine)} time(s) today. "
                  + (f"Last I said: {_first_sentence(mine[-1]['text'])}"
                     if mine else "I was silent."))
        outside_bits = []
        for other in names:
            if other == name:
                continue
            told = [e for e in entries if e.get("speaker") == other
                    and e.get("addressee") == name and e.get("text")]
            if told:
                outside_bits.append(f"{other} said to me: {_first_sentence(told[-1]['text'])}")
        outside = " ".join(outside_bits) if outside_bits else "The others said little to me today."
        walls[name] = {"inside": inside, "outside": outside}
    return walls


def last_chant(project) -> str:
    p = _realm_dir(project) / "last_chant.md"
    return p.read_text().strip() if p.exists() else ""


def walls_for(project, name: str) -> dict:
    return load_json(_realm_dir(project) / "walls.json", {}).get(name, {})


def open_day(project) -> str:
    """light — dawn. Returns the Chant that crossed the night (posted first in the
    Hall), or '' on the first day, which has no yesterday."""
    return last_chant(project)


def close_day(project, entries: list, names: list) -> str:
    """dark — dusk. Fold the day's Hall into the Chant and the walls, persist them,
    advance the day counter. Returns the Chant. Pure projection: same entries in,
    same files out."""
    d = _realm_dir(project)
    (d / "chants").mkdir(parents=True, exist_ok=True)
    n = day_number(project) + 1
    chant = compose_chant(entries, n)
    (d / "chants" / f"day{n}.md").write_text(chant + "\n")
    (d / "last_chant.md").write_text(chant + "\n")
    save_json(d / "walls.json", compose_walls(entries, names))
    save_json(d / "day.json", {"day": n})
    return chant


def todays_hall(project) -> list:
    """The day's Hall so far — the entries from today's sessions and orders, which
    ``dark`` folds into the Chant. (A projection over the transcripts on disk.)"""
    stamp = time.strftime("%Y%m%d")
    entries = []
    sessions = project.root / "sessions"
    if sessions.exists():
        for f in sorted(sessions.glob(f"{stamp}-*.jsonl")):
            entries += _read_jsonl(f)
    orders = project.root / "orders"
    if orders.exists():
        for hp in sorted(orders.glob("*/hall.jsonl")):
            if hp.parent.name.startswith(stamp):
                entries += _read_jsonl(hp)
    if entries:
        return entries
    # After midnight a day that just closed reads empty and the cathedral would
    # show a quiet hall though a day just spoke. Fall back to the most recent hall
    # on disk — the last day that spoke, not today-or-nothing (V1 cathedral notes).
    if orders.exists():
        halls = sorted((p for p in orders.glob("*/hall.jsonl")),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if halls:
            return _read_jsonl(halls[0])
    return entries


def _read_jsonl(path) -> list:
    out = []
    try:
        for ln in path.read_text().splitlines():
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    continue
    except OSError:
        pass
    return out
