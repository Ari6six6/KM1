"""The grimoire — the Wizard's book of claims, the realm's first memory of subjects.

`world.py` is the map of *places* the realm has touched; this is the ledger of
what it has come to *believe*. The difference is the whole point: a narrative
only ever sounds right, so re-reading it teaches nothing — but a claim can be
*wrong*, and a claim the realm is leaning its weight on that turns out wrong is
where the second look earns its keep.

Each claim carries how it is known (its rung — inferred → observed → computed →
executed), a test that would break it, whether it still stands (unchecked → held
→ broken), and which other claims lean on it. From that last thread comes the one
piece of real arithmetic here: which unchecked claim, if it fell, would take the
most of the map down with it — that is the one worth testing next. Plain JSON,
kept honest, mirroring `world.py` in shape and voice.
"""

from __future__ import annotations

import time

from mor.config import load_json, save_json

# The provenance ladder — how a claim is known. Labels, never scores: a number
# here would only be false precision. The rungs still *order*, low trust to high.
RUNGS = ("inferred", "observed", "computed", "executed")
STATUSES = ("unchecked", "held", "broken")


def load(space) -> dict:
    return load_json(space.grimoire_path(), {"subjects": {}})


def save(space, data) -> None:
    save_json(space.grimoire_path(), data)


def _subject(data, subject: str) -> dict:
    return data.setdefault("subjects", {}).setdefault(subject, {"claims": {}})


def _next_id(claims: dict) -> str:
    n = 0
    for k in claims:
        if k.startswith("c") and k[1:].isdigit():
            n = max(n, int(k[1:]))
    return f"c{n + 1}"


def record_claim(space, subject: str, text: str, rung: str = "inferred",
                 test: str = "", depends_on=None) -> str:
    """Write a new claim into the book. Returns its id (c1, c2, …, per subject)."""
    data = load(space)
    claims = _subject(data, subject)["claims"]
    cid = _next_id(claims)
    claims[cid] = {
        "text": text,
        "rung": rung if rung in RUNGS else "inferred",
        "test": test,
        "status": "unchecked",
        "depends_on": [d for d in (depends_on or []) if d in claims],
        "history": [{"day": time.strftime("%Y-%m-%d"),
                     "event": f"recorded ({rung})"}],
    }
    save(space, data)
    return cid


def mark_claim(space, subject: str, claim_id: str, status: str,
               note: str = "", rung=None) -> bool:
    """Mark a claim tested (held/broken/unchecked), optionally raising its rung.
    Returns False if the subject or claim is unknown — a broken claim is *kept*,
    with what broke it in its history, because that is the valuable entry."""
    if status not in STATUSES:
        return False
    data = load(space)
    subj = data.get("subjects", {}).get(subject)
    if not subj or claim_id not in subj.get("claims", {}):
        return False
    claim = subj["claims"][claim_id]
    claim["status"] = status
    if rung in RUNGS:
        claim["rung"] = rung
    event = status if not note else f"{status} — {note}"
    claim.setdefault("history", []).append(
        {"day": time.strftime("%Y-%m-%d"), "event": event})
    save(space, data)
    return True


def _transitive_dependents(claims: dict, cid: str) -> int:
    """How many claims fall if `cid` is wrong: everything that reaches it by
    following depends_on. A BFS over the reverse graph — the honest kernel of
    'knowledge gradient' once the ceremony is stripped away."""
    reverse: dict = {}
    for other, claim in claims.items():
        for dep in claim.get("depends_on", []):
            reverse.setdefault(dep, []).append(other)
    seen, queue = set(), list(reverse.get(cid, []))
    while queue:
        node = queue.pop(0)
        if node in seen:
            continue
        seen.add(node)
        queue.extend(reverse.get(node, []))
    return len(seen)


def _best_candidate(claims: dict):
    """The most load-bearing claim still worth testing in one subject, or None.
    Candidates are unchecked or merely inferred; ties break to the older claim
    (insertion order). Returns (claim_id, dependents) or None."""
    best = None
    for cid, claim in claims.items():  # dict order == insertion order == age
        if claim.get("status") == "unchecked" or claim.get("rung") == "inferred":
            if claim.get("status") == "broken":
                continue
            count = _transitive_dependents(claims, cid)
            if best is None or count > best[1]:
                best = (cid, count)
    return best


def next_to_test(space, subject=None):
    """The single claim worth testing next — within one subject, or across the
    whole book when subject is None. Returns the claim dict with id/subject/
    dependents folded in, or None if nothing is open."""
    data = load(space)
    subjects = data.get("subjects", {})
    names = [subject] if subject is not None else list(subjects)
    winner = None  # (dependents, subject_name, claim_id, claim)
    for name in names:
        claims = subjects.get(name, {}).get("claims", {})
        best = _best_candidate(claims)
        if best is None:
            continue
        cid, count = best
        if winner is None or count > winner[0]:
            winner = (count, name, cid, claims[cid])
    if winner is None:
        return None
    count, name, cid, claim = winner
    return {**claim, "id": cid, "subject": name, "dependents": count}


def summary(space, limit: int = 6) -> str:
    """A compact digest for the faces' system prompt: per subject, the tally by
    status and the one claim most worth testing — spelled out, so a face sees
    where the realm's understanding is load-bearing but unproven."""
    subjects = load(space).get("subjects", {})
    if not subjects:
        return "the grimoire is still blank — no claims recorded yet"
    lines = []
    for name, subj in list(subjects.items())[:limit]:
        claims = subj.get("claims", {})
        held = sum(1 for c in claims.values() if c.get("status") == "held")
        unch = sum(1 for c in claims.values() if c.get("status") == "unchecked")
        broke = sum(1 for c in claims.values() if c.get("status") == "broken")
        tally = f"{held} held, {unch} unchecked, {broke} broken"
        best = next_to_test(space, name)
        if best is not None:
            tally += (f' — most load-bearing unchecked: "{best["text"]}" '
                      f'({best["id"]}, {best["dependents"]} claims lean on it)')
        lines.append(f"[{name}] {tally}")
    return "grimoire: " + "; ".join(lines)


def dump(space, subject=None) -> str:
    """Read the book plainly — one subject's claims, or the list of subjects."""
    subjects = load(space).get("subjects", {})
    if not subjects:
        return "the grimoire is still blank — no claims recorded yet"
    if subject is None:
        return "subjects in the grimoire: " + ", ".join(
            f"{n} ({len(s.get('claims', {}))})" for n, s in subjects.items())
    subj = subjects.get(subject)
    if not subj or not subj.get("claims"):
        return f"no claims recorded under [{subject}] yet"
    out = [f"[{subject}]"]
    for cid, claim in subj["claims"].items():
        deps = claim.get("depends_on") or []
        dep = f" ⟵ {', '.join(deps)}" if deps else ""
        test = f"  (test: {claim['test']})" if claim.get("test") else ""
        out.append(f"  {cid} [{claim.get('status')}/{claim.get('rung')}] "
                   f"{claim.get('text')}{dep}{test}")
    return "\n".join(out)
