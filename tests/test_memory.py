"""Memory — lexical recall over the realm's own past work, wired into prompts."""

from __future__ import annotations

from mor.memory import recall, memory_block
from mor.session import Session
from mor.llm import ScriptClient


def _seed_past_report(project, name, text):
    d = project.root / "orders" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.md").write_text(text)


def test_recall_finds_a_seeded_fact(project):
    _seed_past_report(project, "20260101-000000-old-research",
                      "# Research: rivers\n\nThe east ford is at grid reference 12-Charlie.")
    hits = recall(project, "where is the ford?")
    assert hits and any("12-Charlie" in snip for _, snip in hits)
    assert hits[0][0].startswith("order ")


def test_recall_reads_project_notes(project):
    project.notes_path.write_text("- the api key rotates every 30 days\n")
    hits = recall(project, "how often does the key rotate")
    assert hits and "rotates" in hits[0][1]


def test_recall_is_empty_with_no_corpus_or_no_overlap(project):
    assert recall(project, "anything") == []
    _seed_past_report(project, "20260101-000000-x-research", "apples and oranges")
    assert recall(project, "quantum chromodynamics") == []      # no term overlap
    assert recall(project, "an") == []                          # query too short


def test_memory_is_wired_into_every_prompt(project):
    """R2 acceptance: a face answers using last week's findings without being told
    where to look — the recalled fact lands in the assembled context."""
    _seed_past_report(project, "20260101-000000-old-research",
                      "The east ford is at grid 12-Charlie; the bridge is out.")
    seen = []
    s = Session(project, echo=False,
                client=ScriptClient([{"text": "operator, the ford is at 12-Charlie."}]),
                on_turn=seen.append)
    s.run_task("where is the ford?")
    assert any("12-Charlie" in t["user"] for t in seen)
    assert any("REMEMBERS" in t["user"] for t in seen)


def test_memory_block_is_empty_when_nothing_matches(project):
    assert memory_block(project, "nothing here") == ""
