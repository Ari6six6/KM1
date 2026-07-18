"""The Dreaming — the Thirteenth Evangelism.

Between `dark` and the next `light` the realm does not merely sleep. The Wizard
dreams: the day's knowledge — the Ontology's graph of what-is, the grimoire's
book of claims, the map of the outside — is recombined into **questions no one
asked while awake**. A dream is not memory (that is the Chant) and it is not
belief (that is the grimoire). It is *hypothesis*: the realm writing its own
research agenda overnight, so it wakes with new questions to send the Warrior to
answer.

Three shapes of dream, all real, all standing with no oracle at all:

  bridge    — two things the realm knows, joined only through a third: it holds
              A—B and B—C, but never A—C. The dream proposes the missing edge.
              This is link prediction over the graph — the honest kernel of
              insight: the conclusion no one drew because no single face held
              both premises at once.
  negation  — a claim the realm leans its weight on, turned over: *what stands
              if this is false?* The counterfactual becomes a test the General
              can send out at dawn.
  synthesis — the most-connected thing the realm knows, crossed with the
              freshest ground the Warrior carried home.

The night's dream is written to `dreams/day-NNNN.json` at dusk (structural,
deterministic — no mind required). At the next dawn its questions are **seeded
into the grimoire** (rung inferred, status unchecked) and posted into the Hall
before the day's first word — so the realm literally wakes into its own
questions, and the General's audit finds them load-bearing and unproven, and
sends the Warrior to chase what the realm dreamed.

A served mind dreams richer: it is handed the same structural visions and voices
them, but it may not invent the ground — the seeds stay graph-derived, honest.
"""

from __future__ import annotations

import json

from mor import grimoire, world
from mor.config import load_json, save_json

_DREAM_SUBJECT = "the dreaming"
_MAX_VISIONS = 3


# --------------------------------------------------------------------- the graph
def _adjacency(triples: list) -> dict:
    """Undirected neighbour sets from [(s, p, o, w), ...]."""
    adj: dict = {}
    for s, p, o, _w in triples:
        if s == o:
            continue
        adj.setdefault(s, {}).setdefault(o, set()).add(p)
        adj.setdefault(o, {}).setdefault(s, set()).add(p)
    return adj


def _bridges(adj: dict, limit: int = 4) -> list:
    """Pairs (A, C) with no direct edge but a shared neighbour B — ranked by how
    many neighbours they share, then by their combined degree. The realm's own
    missing edges, most-supported first. Deterministic."""
    names = sorted(adj)
    seen, cand = set(), []
    for a in names:
        for c in names:
            if a >= c:                       # unordered pair, once
                continue
            if c in adj.get(a, {}):          # already linked — nothing to dream
                continue
            common = sorted(set(adj.get(a, {})) & set(adj.get(c, {})))
            if not common:
                continue
            key = (a, c)
            if key in seen:
                continue
            seen.add(key)
            deg = len(adj.get(a, {})) + len(adj.get(c, {}))
            cand.append((len(common), deg, a, c, common))
    cand.sort(key=lambda t: (-t[0], -t[1], t[2], t[3]))
    return cand[:limit]


# ------------------------------------------------------------------- the visions
def _vision_bridge(a: str, c: str, via: list) -> dict:
    b = via[0]
    return {
        "kind": "bridge",
        "text": f"Does {a} bear on {c}? The realm touches both through {b}, "
                f"yet nothing binds them directly.",
        "why": f"{a} — {b} — {c} stands in the graph; {a} — {c} does not.",
        "seed": {
            "text": f"{a} is connected to {c} (bridged through {b})",
            "test": f"find a direct link between {a} and {c}, or show there is none",
        },
    }


def _vision_negation(claim: dict) -> dict:
    return {
        "kind": "negation",
        "text": f"What still stands if \"{claim['text']}\" is false?",
        "why": f"the realm leans on {claim['id']} in [{claim['subject']}] "
               f"({claim.get('dependents', 0)} claim(s) rest on it), yet it is "
               f"{claim.get('status', 'unchecked')}.",
        "seed": None,  # points at an existing claim to test — seeds nothing new
        "claim": {"subject": claim["subject"], "id": claim["id"]},
    }


def _vision_synthesis(entity: str, place: str) -> dict:
    return {
        "kind": "synthesis",
        "text": f"What has {entity} to do with {place}?",
        "why": f"{entity} is the most-connected thing the realm knows; {place} is "
               f"the freshest ground the Warrior brought home.",
        "seed": {
            "text": f"{entity} is connected to {place}",
            "test": f"send a sortie that tests whether {entity} bears on {place}",
        },
    }


def _weave(visions: list) -> str:
    """A single plain line naming what the night turned over — the offline
    dream's own voice, deterministic."""
    if not visions:
        return "The well was dark tonight; the realm slept without a dream."
    subjects = []
    for v in visions:
        if v["kind"] == "bridge":
            subjects.append(v["text"].split("?")[0].replace("Does ", "").strip())
        elif v["kind"] == "negation":
            subjects.append("a belief it leans on")
        elif v["kind"] == "synthesis":
            subjects.append(v["text"].split("?")[0].replace("What has ", "").strip())
    return ("In the night the realm turned over " + "; ".join(subjects[:3])
            + " — and woke with questions where the day had only answers.")


# -------------------------------------------------------------- the dream itself
def dream(space, backend=None, day: int = 0) -> dict:
    """Compose the night's dream from the realm's own knowledge. Structural and
    deterministic (no mind needed); a ServedBackend, if attached, voices the
    weave but never invents the ground. Writes dreams/day-NNNN.json, returns the
    record. Never raises — a night that cannot dream sleeps honestly."""
    try:
        visions = _compose(space)
    except Exception:  # noqa: BLE001 — a dream never breaks the dusk that spawns it
        visions = []
    how = "hashed"
    woven = _weave(visions)
    # A served mind dreams the WORDS richer; the seeds stay graph-derived.
    served = _served_weave(backend, visions)
    if served:
        woven, how = served, "mind"
    record = {"day": int(day), "how": how, "woven": woven, "visions": visions}
    try:
        save_json(space.dream_path(day), record)
    except Exception:  # noqa: BLE001
        pass
    return record


def _compose(space) -> list:
    from mor import ontology
    conn = ontology.connect(space)
    try:
        triples = [tuple(r) for r in conn.execute(
            "SELECT subject, predicate, object, weight FROM triples").fetchall()]
        ents = conn.execute(
            "SELECT name, mentions FROM entities ORDER BY mentions DESC, name").fetchall()
    finally:
        conn.close()

    adj = _adjacency(triples)
    visions: list = []
    used: set = set()

    # 1. bridge — the realm's own missing edges
    for _n, _d, a, c, via in _bridges(adj):
        if a in used and c in used:
            continue
        visions.append(_vision_bridge(a, c, via))
        used.update((a, c))
        break  # one strong bridge is a dream; a dozen is noise

    # 2. negation — turn over the most load-bearing unproven belief
    best = grimoire.next_to_test(space)
    if best is not None:
        visions.append(_vision_negation(best))

    # 3. synthesis — the hub of what-is, met with the newest ground
    places = world.load(space).get("places", {})
    if adj and places:
        hub = max(adj, key=lambda n: (len(adj[n]), n))
        freshest = max(places.values(),
                       key=lambda p: (p.get("last_seen", ""), p.get("domain", "")))
        pdom = freshest.get("domain", "")
        if pdom and pdom.lower() != hub.lower():
            visions.append(_vision_synthesis(hub, pdom))

    return visions[:_MAX_VISIONS]


def _served_weave(backend, visions: list):
    """If a real oracle is attached, let it voice the dream — a few sentences over
    the structural visions. Any failure falls back to the deterministic weave."""
    from mor.engine.backend import ServedBackend
    if not isinstance(backend, ServedBackend) or not visions:
        return None
    body = "\n".join(f"- {v['text']}" for v in visions)
    prompt = (
        "You are the Wizard, dreaming. Below are the questions the realm's own "
        "knowledge threw up in the night — do not add facts, do not answer them, "
        "only voice them as a short dream (three or four sentences, plain, a "
        "little strange, no preamble). Then stop.\n\n" + body)
    try:
        res = backend.chat([{"role": "user", "content": prompt}])
        text = (res.content or "").strip()
        return text or None
    except Exception:  # noqa: BLE001 — the mind's voice is a gift, never a fault
        return None


# ----------------------------------------------------------- reading it at dawn
def seed_into_dawn(space, day_that_ended: int) -> dict:
    """At first light, take the dream of the night just past: seed its questions
    into the grimoire (so the General's audit finds them load-bearing and
    unproven) and return the record for posting into the Hall. Returns {} if
    there was no dream to read."""
    rec = load_json(space.dream_path(day_that_ended), {})
    if not rec or not rec.get("visions"):
        return {}
    seeded = []
    for v in rec["visions"]:
        seed = v.get("seed")
        if not seed:
            continue
        cid = grimoire.record_claim(
            space, _DREAM_SUBJECT, seed["text"], rung="inferred",
            test=seed.get("test", ""))
        v["seeded_as"] = cid
        seeded.append(cid)
    rec["seeded"] = seeded
    return rec


def render_line(rec: dict) -> str:
    """The one Hall line a dream speaks at dawn — the weave and its first question."""
    if not rec or not rec.get("visions"):
        return ""
    first = rec["visions"][0]["text"]
    return f"{rec.get('woven', '').strip()}  The first question: {first}"


def latest(space, upto_day: int = 9999) -> dict:
    """The most recent dream on record at or before a day — for `dream` and the
    Cathedral."""
    best = {}
    d = space.root / "dreams"
    if not d.is_dir():
        return {}
    for p in sorted(d.glob("day-*.json")):
        rec = load_json(p, {})
        if rec and int(rec.get("day", 0)) <= upto_day:
            best = rec
    return best
