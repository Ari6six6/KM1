"""R3c — the Dreaming: a knowledge projection recombined into traceable questions."""

from __future__ import annotations

import json
import time

from mor.dream import (extract, components, bridge, negation, synthesis,
                       is_question, dream, dream_questions)
from mor.ledger import events
from mor.llm import ScriptClient

# a scripted day with a known shape: disconnected clusters + one contradiction +
# a near-duplicate entity pair
DAY = [
    {"seq": 0, "text": "alpha uses beta"},
    {"seq": 1, "text": "gamma uses delta"},
    {"seq": 2, "text": "epsilon contradicts zeta"},
    {"seq": 3, "text": "orion-7 solves latency"},
    {"seq": 4, "text": "orion7 blocks noise"},
]


def test_extraction_has_provenance_and_the_closed_vocabulary():
    edges = extract(DAY)
    assert edges and all({"subject", "relation", "object", "source_event"} <= set(e) for e in edges)
    assert all(e["relation"] in
               ("uses", "prefers", "blocks", "solves", "depends_on", "contradicts", "learned")
               for e in edges)
    assert any(e["subject"] == "alpha" and e["object"] == "beta" for e in edges)


def test_the_night_produces_traceable_bridge_and_negation_questions():
    edges = extract(DAY)
    comps = components(edges)
    bridges = bridge(edges, comps)
    negations = negation(edges)
    assert len(bridges) >= 1 and len(negations) >= 1        # acceptance #1
    assert all(q["source"] for q in bridges + negations)     # each traceable to its edges
    assert negations[0]["source"] == ["event:2"]             # traces to the contradiction


def test_offline_and_model_extraction_share_the_schema():
    offline = extract(DAY)                                    # DEMO, zero model
    assert offline and all({"subject", "relation", "object", "source_event"} <= set(e) for e in offline)
    payload = json.dumps([{"subject": "alpha", "relation": "uses", "object": "beta",
                           "source_event": "event:0"}])
    modeled = extract(DAY, client=ScriptClient([{"text": payload}]))
    assert modeled and all({"subject", "relation", "object", "source_event"} <= set(e) for e in modeled)
    assert modeled[0]["relation"] == "uses"                  # same schema, served mind


def test_every_dream_seed_is_a_question_never_an_assertion():
    edges = extract(DAY)
    seeds = bridge(edges) + negation(edges) + synthesis(edges)
    assert seeds
    assert all(is_question(q["text"]) for q in seeds)        # acceptance #3 (guard)


def test_synthesis_spots_near_duplicate_entities():
    qs = synthesis(extract(DAY))
    assert any("orion-7" in q["text"] and "orion7" in q["text"] for q in qs)


def test_dream_records_events_and_seeds_the_dawn(project):
    stamp = time.strftime("%Y%m%d") + "-000000"
    sp = project.session_path(stamp)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text("\n".join(json.dumps({"speaker": "lead", "addressee": "worker",
                                        "text": t["text"], "seq": t["seq"]}) for t in DAY))
    result = dream(project)
    assert result["mode"] == "demo"
    recorded = events(project, "dream.question")
    assert recorded and all(e.get("source") for e in recorded)   # provenance in the ledger
    assert dream_questions(project)                              # persisted for `mor light`
    assert all(is_question(q["text"]) for q in dream_questions(project))
