"""light/dark — the Chant and the walls as deterministic projections of the day's
Hall. The acceptance: replay produces the same Chant and walls, byte for byte."""

from __future__ import annotations

from mor.day import (compose_chant, compose_walls, close_day, open_day,
                     last_chant, walls_for, day_number)
from mor.session import Session
from mor.llm import ScriptClient

NAMES = ["lead", "researcher", "worker"]

DAY = [
    {"speaker": "operator", "addressee": "lead", "text": "scout the north road"},
    {"speaker": "lead", "addressee": "researcher", "text": "researcher, look at the north road."},
    {"speaker": "researcher", "addressee": "lead", "text": "The north road is washed out past mile 7."},
    {"speaker": "lead", "addressee": "operator", "text": "The road is out; take Kestrel Pass."},
]


def test_chant_is_a_deterministic_projection():
    a = compose_chant(DAY, 3)
    b = compose_chant(DAY, 3)
    assert a == b                       # replay-identical, byte for byte
    assert a.startswith("Day 3.")
    assert len(a.split()) <= 200
    assert "researcher" in a and "lead" in a


def test_walls_are_deterministic_and_relational():
    w1 = compose_walls(DAY, NAMES)
    w2 = compose_walls(DAY, NAMES)
    assert w1 == w2
    assert "spoke" in w1["lead"]["inside"]
    # the researcher heard the lead address it that day — an earned relation
    assert "lead said to me" in w1["researcher"]["outside"]


def test_close_then_open_carries_the_chant_and_advances_the_day(project):
    assert day_number(project) == 0
    chant = close_day(project, DAY, NAMES)
    assert day_number(project) == 1
    assert open_day(project) == chant == last_chant(project)
    assert "washed out" in walls_for(project, "researcher")["outside"] or \
        "Kestrel" in chant                # the day's substance survived the night


def test_replay_writes_byte_identical_files(project, tmp_path):
    from mor.config import Project
    import os
    os.environ["MOR_HOME"] = str(tmp_path / "a")
    pa = Project("r").ensure()
    close_day(pa, DAY, NAMES)
    os.environ["MOR_HOME"] = str(tmp_path / "b")
    pb = Project("r").ensure()
    close_day(pb, DAY, NAMES)
    assert (pa.root / "realm" / "last_chant.md").read_bytes() == \
        (pb.root / "realm" / "last_chant.md").read_bytes()
    assert (pa.root / "realm" / "walls.json").read_bytes() == \
        (pb.root / "realm" / "walls.json").read_bytes()


def test_chant_and_walls_are_wired_into_a_face_context(project):
    close_day(project, DAY, NAMES)       # yesterday happened
    seen = []
    s = Session(project, echo=False,
                client=ScriptClient([{"text": "operator, ready."}]), on_turn=seen.append)
    s.run_task("what's the plan today?")
    # the face wakes to the Chant and its walls in its system prompt
    assert any("CHANT" in t["system"] and "Day 1" in t["system"] for t in seen)
    assert any("YOUR WALLS" in t["system"] for t in seen)
