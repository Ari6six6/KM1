"""R2.1 — the mind registry + the selection window (BYO-box primary path)."""

from __future__ import annotations

from mor import mind
from mor.session import Session


def _register(project, label, port, model="glm"):
    mind.register_box(project, label=label, base_url=f"http://localhost:{port}/v1",
                      model=model, ssh_host="1.2.3.4", ssh_port="22", rate=0.0)


def test_adopt_registers_a_box_in_the_ledger(project):
    _register(project, "byo-host-1", 8080)
    boxes = mind.boxes(project)
    assert [b["label"] for b in boxes] == ["byo-host-1"]
    assert boxes[0]["state"] == "serving" and boxes[0]["base_url"].endswith(":8080/v1")


def test_chosen_routes_by_count_and_active(project):
    assert mind.chosen(project) == (None, False)          # 0 serving → offline
    _register(project, "byo-a-1", 8080)
    box, needs = mind.chosen(project)
    assert box["label"] == "byo-a-1" and needs is False   # exactly 1 → auto-route
    _register(project, "byo-b-1", 8081)
    assert mind.chosen(project) == (None, True)            # >1, no active → select
    mind.set_active(project, "byo-b-1")
    box, needs = mind.chosen(project)
    assert box["label"] == "byo-b-1" and needs is False    # active resolves it


def test_active_mind_persists_across_a_reload(project):
    _register(project, "byo-a-1", 8080)
    _register(project, "byo-b-1", 8081)
    mind.set_active(project, "byo-a-1")
    from mor.config import Project
    reloaded = Project(project.name)                       # a fresh handle (as after restart)
    assert mind.active(reloaded) == "byo-a-1"


def test_selection_window_prompts_and_remembers(project):
    _register(project, "byo-a-1", 8080)
    _register(project, "byo-b-1", 8081)
    lines = []
    chosen = mind.prompt_selection(project, ask=lambda _p: "2", out=lines.append)
    assert chosen["label"] == "byo-b-1"
    assert mind.active(project) == "byo-b-1"               # the choice is remembered
    assert any("which one" in ln for ln in lines)


def test_session_routes_to_the_active_boxs_endpoint(project):
    _register(project, "byo-a-1", 8080)
    _register(project, "byo-b-1", 8099)
    mind.set_active(project, "byo-b-1")
    s = Session(project, echo=False)                       # no explicit client
    assert s.mode == "model"
    assert s.client.base_url == "http://localhost:8099/v1"


def test_one_serving_box_auto_routes_without_a_picker(project):
    _register(project, "byo-only-1", 8077)
    s = Session(project, echo=False)
    assert s.mode == "model" and s.client.base_url.endswith(":8077/v1")


def test_release_takes_a_byo_box_out_of_serving(project):
    _register(project, "byo-a-1", 8080)
    assert mind.release(project, "byo-a-1")["label"] == "byo-a-1"
    assert mind.serving(project) == []
    assert mind.release(project, "nope") is None


def test_rate_joins_the_box_to_the_cost_ledger(project):
    _register(project, "byo-a-1", 8080)
    assert mind.set_rate(project, "byo-a-1", 0.55) is True
    assert next(b for b in mind.boxes(project) if b["label"] == "byo-a-1")["rate"] == 0.55
