"""Orders — the unit of work: executed through the Hall, delivered as an artifact,
with state that is a projection of an event log (so a restart resumes it)."""

from __future__ import annotations

from mor.order import OrderStore, run_order, _task_for
from mor.llm import Client, ChatResult
from mor.llm import ScriptClient


def test_research_order_delivers_an_artifact_offline(project):
    order = run_order(project, "research", "summarize the workspace", echo=False)
    assert order.state == "delivered"
    arts = order.artifacts()
    assert len(arts) == 1 and arts[0].name == "report.md"
    body = arts[0].read_text()
    assert "summarize the workspace" in body
    assert "DEMO" in body            # offline is labelled honestly


def test_order_state_is_a_projection_replayed_from_disk(project):
    order = run_order(project, "research", "map the ford", echo=False)
    oid = order.id
    # a fresh store (as a restarted daemon would) rebuilds state from the events
    reloaded = OrderStore(project).load(oid)
    assert reloaded is not None
    assert reloaded.state == "delivered"
    assert reloaded.brief == "map the ford"
    assert [p.name for p in reloaded.artifacts()] == ["report.md"]


def test_order_lifecycle_events_are_recorded_in_order(project):
    order = run_order(project, "research", "recon", echo=False)
    kinds = [e["kind"] for e in order.events]
    # the gate loop: the rubric is frozen at planned, before any work
    assert kinds[:3] == ["received", "planned", "rubric"]
    for k in ("executing", "verifying", "fitness"):
        assert k in kinds
    assert kinds[-1] == "delivered"
    assert [e["seq"] for e in order.events] == list(range(len(order.events)))


def test_rubric_is_an_event_never_spoken_into_the_hall(project):
    # Wall 2: the rubric rides the event log, never the transcript the crew reads.
    order = run_order(project, "research", "top async http libraries with sources",
                      echo=False)
    rubric = next(e for e in order.events if e["kind"] == "rubric")
    assert rubric["seq"] < next(e["seq"] for e in order.events if e["kind"] == "executing")
    hall = order.hall_path.read_text() if order.hall_path.exists() else ""
    assert "required_fact" not in hall and '"checks"' not in hall


def test_offline_order_gate_is_advisory_and_still_delivers(project):
    # No calibration on a fresh realm → advisory: scored, flagged, delivered (DEMO).
    order = run_order(project, "research", "anything at all", echo=False)
    assert order.state == "delivered"
    delivered = next(e for e in order.events if e["kind"] == "delivered")
    assert delivered["gate"] == "advisory"
    assert "score" in delivered
    fit = next(e for e in order.events if e["kind"] == "fitness")
    assert "vector" in fit and isinstance(fit["scalar"], (int, float))


def test_order_lists_newest_first(project):
    a = run_order(project, "research", "first", echo=False)
    b = run_order(project, "research", "second", echo=False)
    listed = [o.id for o in OrderStore(project).list()]
    assert set(listed) == {a.id, b.id}
    assert listed[0] == b.id          # newest first


def test_scripted_order_executes_through_the_hall(project):
    script = ScriptClient([
        {"text": "researcher, note that the ford is out. "},
        {"text": "Noted — the east ford is out; route north. lead, over to you."},
        {"text": "operator, the ford is out — the report routes north."},
    ])
    order = run_order(project, "research", "is the ford passable?",
                      echo=False, client=script)
    assert order.state == "delivered"
    body = order.artifacts()[0].read_text()
    assert "route north" in body      # the crew's conclusion is in the artifact
    assert "How the crew worked (the Hall)" in body


def test_order_kinds_frame_distinct_tasks():
    build = _task_for("build", "a csv deduper")
    fetch = _task_for("fetch", "the PDFs on that page")
    research = _task_for("research", "http libraries")
    assert "test" in build and "csv deduper" in build
    assert "web" in fetch and "TAINTED" in fetch
    assert "sourced" not in build and "test" not in research


def test_build_and_fetch_orders_deliver(project):
    for kind in ("build", "fetch"):
        order = run_order(project, kind, f"a {kind} job", echo=False)
        assert order.state == "delivered"
        assert order.artifacts()[0].read_text().startswith(f"# {kind.title()}:")


def test_a_failing_turn_fails_the_order_not_the_process(project):
    class Boom(Client):
        def chat(self, messages, tools=None):
            raise RuntimeError("model exploded")

    order = run_order(project, "research", "will it fail?", echo=False, client=Boom())
    assert order.state == "failed"
    assert any(e["kind"] == "failed" and "RuntimeError" in e.get("reason", "")
               for e in order.events)
