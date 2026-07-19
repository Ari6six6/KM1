"""The Dreaming — the night is for questions.

The day is for answers; the Forge is for strength; the Dreaming is for wonder. At
dusk the realm folds the day into a small knowledge graph and recombines it into
**questions no one asked while awake** — which seed the next dawn and aim the Forge.
Curiosity aims; the benchmark decides.

Three operations, each emitting *questions, never assertions*:

  bridge    — two clusters with no path between them → "what connects A and B?"
  negation  — two claims that contradict → "which is true?"
  synthesis — two near-duplicate entities → "are A and A′ the same thing?"

The graph is a projection of the day's Hall + order reports. Offline it is built by
a deterministic relation-pattern extractor, labelled DEMO — an honest scaffold,
never presented as more. With a served mind, model-assisted extraction fills the
same schema — (subject, relation, object, source_event) — and provenance is
mandatory: every edge, and every question, names the event it came from.
"""

from __future__ import annotations

import json
import re

from mor.config import load_json, save_json

RELATIONS = ("uses", "prefers", "blocks", "solves", "depends_on", "contradicts", "learned")
_SURFACE = {"depends on": "depends_on"}
_PAT = re.compile(
    r"\b([a-z][a-z0-9_-]{1,30})\s+(uses|prefers|blocks|solves|depends on|contradicts|learned)\s+"
    r"([a-z][a-z0-9_-]{1,30})\b", re.IGNORECASE)


# -- extraction (the knowledge projection) ----------------------------------
def _sources(entries, reports):
    src = []
    for i, e in enumerate(entries or []):
        src.append((f"event:{e.get('seq', i)}", e.get("text", "")))
    for j, r in enumerate(reports or []):
        src.append((f"report:{j}", r))
    return src


def _extract_offline(entries, reports=None) -> list:
    edges = []
    for sid, text in _sources(entries, reports):
        for m in _PAT.finditer(text):
            rel = m.group(2).lower()
            edges.append({"subject": m.group(1).lower(),
                          "relation": _SURFACE.get(rel, rel),
                          "object": m.group(3).lower(), "source_event": sid})
    return edges


def _find_json_array(text: str) -> str:
    start, end = text.find("["), text.rfind("]")
    return text[start:end + 1] if 0 <= start < end else "[]"


def _extract_model(entries, reports, client) -> list:
    corpus = "\n".join(f"[event:{e.get('seq', i)}] {e.get('text', '')}"
                       for i, e in enumerate(entries or []))
    prompt = ("Extract (subject, relation, object, source_event) triples from the text. "
              "Use only these relations: " + ", ".join(RELATIONS) + ". Name the "
              "source_event for each. Return only a JSON array.\n\n" + corpus)
    res = client.chat([{"role": "system", "content": "You extract a knowledge graph."},
                       {"role": "user", "content": prompt}])
    edges = []
    try:
        for d in json.loads(_find_json_array(res.content or "[]")):
            if isinstance(d, dict) and {"subject", "relation", "object"} <= set(d):
                edges.append({"subject": str(d["subject"]).lower(),
                              "relation": str(d["relation"]),
                              "object": str(d["object"]).lower(),
                              "source_event": d.get("source_event", "model")})
    except (ValueError, TypeError):
        pass
    return edges


def extract(entries, reports=None, client=None) -> list:
    """Edges into one schema — (subject, relation, object, source_event). Offline is
    deterministic patterns; a served mind fills the same schema."""
    if client is not None:
        return _extract_model(entries, reports, client)
    return _extract_offline(entries, reports)


# -- the graph shape --------------------------------------------------------
def components(edges) -> list:
    """Connected clusters of entities (union-find over the edges)."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    ents = set()
    for e in edges:
        ents.add(e["subject"])
        ents.add(e["object"])
        parent[find(e["subject"])] = find(e["object"])
    groups = {}
    for x in ents:
        groups.setdefault(find(x), []).append(x)
    return [sorted(g) for g in groups.values()]


# -- the dream cycle (questions, never assertions) --------------------------
def bridge(edges, comps=None) -> list:
    comps = comps if comps is not None else components(edges)
    comps = [c for c in comps if c]
    out = []
    for i in range(len(comps) - 1):
        a, b = comps[i][0], comps[i + 1][0]
        out.append({"kind": "bridge", "text": f"what connects {a} and {b}?",
                    "source": [a, b]})
    return out[:3]


def negation(edges) -> list:
    out = []
    for e in edges:
        if e["relation"] == "contradicts":
            out.append({"kind": "negation",
                        "text": f"which is true — {e['subject']} or {e['object']}?",
                        "source": [e["source_event"]]})
    return out


def _similar(a: str, b: str) -> bool:
    na, nb = a.replace("-", "").replace("_", ""), b.replace("-", "").replace("_", "")
    return a != b and (na == nb or (len(na) > 3 and (na in nb or nb in na)))


def synthesis(edges) -> list:
    ents = sorted({e["subject"] for e in edges} | {e["object"] for e in edges})
    out = []
    for i in range(len(ents)):
        for j in range(i + 1, len(ents)):
            if _similar(ents[i], ents[j]):
                out.append({"kind": "synthesis",
                            "text": f"are {ents[i]} and {ents[j]} the same thing?",
                            "source": [ents[i], ents[j]]})
    return out[:3]


def is_question(text: str) -> bool:
    """A dream seed asks; it never asserts."""
    return text.strip().endswith("?")


def _dream_path(project):
    return project.root / "realm" / "dream.json"


def dream(project, client=None) -> dict:
    """Fold the day into a graph, wonder over it, and seed the questions — recorded
    as ledger events with provenance, and persisted for `mor light` to post."""
    from mor.day import todays_hall
    from mor.order import OrderStore
    from mor.ledger import record

    entries = todays_hall(project)
    reports = []
    for o in OrderStore(project).list()[:50]:
        for p in o.artifacts():
            if p.name == "report.md":
                reports.append(p.read_text())
    edges = extract(entries, reports, client=client)
    comps = components(edges)
    questions = bridge(edges, comps) + negation(edges) + synthesis(edges)
    mode = "model" if client is not None else "demo"
    for q in questions:
        record(project, "dream.question", text=q["text"], dream_kind=q["kind"],
               source=q.get("source"), mode=mode)
    save_json(_dream_path(project),
              {"mode": mode, "questions": [{"text": q["text"], "kind": q["kind"],
                                            "source": q.get("source")} for q in questions]})
    return {"edges": edges, "questions": questions, "mode": mode}


def dream_questions(project) -> list:
    return load_json(_dream_path(project), {"questions": []}).get("questions", [])


def clear_dream(project) -> None:
    save_json(_dream_path(project), {"questions": []})
