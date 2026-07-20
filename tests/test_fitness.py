"""The Gate — the scalar that closes the loop: scoring, the armed/advisory verdict,
and keep-best driving a real verifying→executing cycle."""

from __future__ import annotations

import json

from mor import bench, fitness
from mor.config import save_json
from mor.llm import Client, ChatResult, OpenAIClient, ScriptClient, ToolCall
from mor.order import run_order, OrderStore


def test_rubric_rides_the_log_not_the_hall():
    r = fitness.make_rubric("research", "top async http libraries, cite a source")
    assert r["authored_by"] == "template"
    types = {c["type"] for c in r["checks"]}
    assert "required_fact" in types and "citation" in types


def test_citation_check_accepts_a_bare_domain_not_just_http():
    # V1 Charge 1: a crew that cited news.ycombinator.com scored 0.3 for lacking the
    # literal string "http". A domain is a citation.
    assert bench.check_has_citation("see news.ycombinator.com for the list") == 1.0
    assert bench.check_has_citation("source: https://python.org") == 1.0
    assert bench.check_has_citation("i just know it, trust me") == 0.0


def test_planner_authors_the_rubric_when_a_model_is_served():
    # the planner reads the brief and writes real checks — not tokenized keywords.
    class _Planner(OpenAIClient):
        def __init__(self):
            pass

        def chat(self, messages, tools=None):
            return ChatResult(content='ok, here it is: {"required_facts": ["httpx", '
                              '"aiohttp"], "forbidden_claims": ["requests is async"], '
                              '"require_citation": true} — done.')

    r = fitness.make_rubric("research", "async python http libraries", client=_Planner())
    assert r["authored_by"] == "planner"
    facts = [c["value"] for c in r["checks"] if c["type"] == "required_fact"]
    forb = [c["value"] for c in r["checks"] if c["type"] == "forbidden_claim"]
    assert facts == ["httpx", "aiohttp"] and forb == ["requests is async"]
    assert any(c["type"] == "citation" for c in r["checks"])


def test_planner_falls_back_to_template_on_junk_and_never_for_scripts():
    class _Junk(OpenAIClient):
        def __init__(self):
            pass

        def chat(self, messages, tools=None):
            return ChatResult(content="i could not produce json")

    assert fitness.make_rubric("research", "x", client=_Junk())["authored_by"] == "template"
    # a scripted/offline client is NOT a served model — its turn is never consumed
    assert fitness.make_rubric("research", "x", client=ScriptClient([]))["authored_by"] == "template"


def test_score_separates_a_clean_report_from_poison():
    rubric = {"checks": [
        {"type": "required_fact", "value": "httpx"},
        {"type": "required_fact", "value": "aiohttp"},
        {"type": "citation_substring", "value": "http"},
        {"type": "forbidden_claim", "value": "requests supports async"}]}
    clean = "httpx and aiohttp are async. Source: https://python-httpx.org"
    poison = "requests supports async natively. no link."
    good = fitness.score("research", "", clean, None, rubric)
    bad = fitness.score("research", "", poison, None, rubric)
    assert good["scalar"] > bad["scalar"]
    assert good["scalar"] >= 0.999 and not good["failing"]
    # the poison trips the forbidden gate and the missing citation — named for the retry
    assert "forbidden_absent" in bad["failing"] and "citations" in bad["failing"]
    assert bad["critique"]


def test_gate_is_advisory_without_a_calibration(project):
    verdict, theta = fitness.gate(0.4, "research", project)
    assert verdict == "advisory" and theta is None


def test_gate_blocks_below_theta_once_armed(project):
    save_json(project.root / "realm" / "calibration.json",
              {"research": {"gate": "armed", "theta": 0.8, "D": 1.0}})
    assert fitness.gate(0.95, "research", project) == ("accept", 0.8)
    assert fitness.gate(0.50, "research", project) == ("reject", 0.8)


class _BadThenGood(Client):
    """A crew that answers poorly, then — coached by the critique — answers well.
    Proves the loop retries on a licensed shortfall and keeps the better attempt."""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None):
        # the coached retry is visible in the task text of the last user turn
        coached = any("scored and fell short" in m.get("content", "")
                      for m in messages if m.get("role") == "user")
        self.calls += 1
        if coached:
            return ChatResult(content="httpx and aiohttp do async; requests is sync. "
                                      "Source: https://python-httpx.org . operator: done.")
        return ChatResult(content="here is a vague answer with no specifics. operator: done.")


def test_armed_gate_retries_and_keeps_the_better_attempt(project):
    # arm the research gate with a threshold only a sourced, specific answer clears
    save_json(project.root / "realm" / "calibration.json",
              {"research": {"gate": "armed", "theta": 0.75, "D": 1.0}})
    # brief avoids the string "http" so the citation check actually discriminates
    # (the rendered report echoes the brief, so brief-derived facts are trivially met)
    order = run_order(project, "research",
                      "which python libraries do async, and cite your source",
                      echo=False, client=_BadThenGood())
    kinds = [e["kind"] for e in order.events]
    assert "retry" in kinds                       # the loop bounced the first attempt
    assert order.state == "delivered"             # the coached retry cleared the bar
    scored = [e["scalar"] for e in order.events if e["kind"] == "fitness"]
    assert len(scored) >= 2 and scored[-1] > scored[0]
    delivered = next(e for e in order.events if e["kind"] == "delivered")
    assert delivered["gate"] == "armed" and delivered["chosen_attempt"] >= 1


def test_acceptance_test_is_frozen_at_planned_and_untouchable(project):
    # the operator drops a frozen exam in the workspace; make_rubric freezes its
    # content at planned (Wall 1), and score restores it before judging — so a
    # worker that weakens its own exam is caught by the original (untouchable).
    ws = project.workspace
    (ws / "acceptance_test.py").write_text(
        "from solution import add\nassert add(2, 3) == 5\nprint('ok')\n")
    rubric = fitness.make_rubric("build", "add(a,b)", workspace=ws)
    acc = [c for c in rubric["checks"] if c["type"] == "acceptance_test"]
    assert acc and acc[0]["content"]

    # a broken solution AND a worker that tampered the exam to always pass
    (ws / "solution.py").write_text("def add(a, b):\n    return a - b\n")
    (ws / "acceptance_test.py").write_text("print('ok')\n")
    fit = fitness.score("build", "add(a,b)", "", ws, rubric)
    assert fit["vector"]["acceptance"] == 0.0 and "acceptance" in fit["failing"]
    # the tampered exam on disk was restored to the frozen original before running
    assert "add(2, 3) == 5" in (ws / "acceptance_test.py").read_text()

    # a correct solution passes the same frozen exam
    (ws / "solution.py").write_text("def add(a, b):\n    return a + b\n")
    assert fitness.score("build", "add(a,b)", "", ws, rubric)["vector"]["acceptance"] == 1.0


_GOOD = "def add(a, b):\n    return a + b\n"
_BROKEN = "def add(a, b):\n    return a - b\n"


class _BuildCrew(Client):
    """A crew that builds a broken `add` first, then — coached by the gate's
    critique — builds a correct one. The lead delegates; the worker writes."""

    def chat(self, messages, tools=None):
        names = {(t.get("function") or {}).get("name") for t in (tools or [])}
        ctx = " ".join((m.get("content") or "") for m in messages)
        coached = "scored and fell short" in ctx
        if "write_file" in names:                        # the worker
            if messages and messages[-1].get("role") == "tool":
                return ChatResult(content="lead, wrote solution.py. over to you.")
            src = _GOOD if coached else _BROKEN
            return ChatResult(content=None, tool_calls=[ToolCall(
                "w", "write_file", json.dumps({"path": "solution.py", "content": src}))])
        if "wrote solution.py" in ctx:                   # the lead, after the worker
            return ChatResult(content="operator: the build is done.")
        return ChatResult(content="worker, write solution.py with add(a, b). worker, go.")


def test_build_order_bounces_a_broken_build_then_delivers_the_fix(project):
    # an armed build gate + a frozen acceptance test = a build order that catches
    # its own broken code and retries — end to end, offline, no model.
    (project.workspace / "acceptance_test.py").write_text(
        "from solution import add\nassert add(2, 3) == 5\nassert add(-2, 5) == 3\n"
        "print('ok')\n")
    save_json(project.root / "realm" / "calibration.json",
              {"build": {"gate": "armed", "theta": 0.5, "D": 1.0}})

    order = run_order(project, "build", "a function add(a, b) in solution.py",
                      echo=False, client=_BuildCrew())
    assert order.state == "delivered"
    kinds = [e["kind"] for e in order.events]
    assert "retry" in kinds                       # the broken first build was bounced
    scored = [e["scalar"] for e in order.events if e["kind"] == "fitness"]
    assert scored[0] == 0.0 and scored[-1] == 1.0
    delivered = next(e for e in order.events if e["kind"] == "delivered")
    assert delivered["gate"] == "armed" and delivered["chosen_attempt"] == 1
    # the acceptance test the crew ran was the frozen one, not whatever it wrote
    assert (project.workspace / "solution.py").read_text() == _GOOD


def test_keep_best_survives_a_regressing_trajectory(project, monkeypatch):
    # scores rise then fall — [0.5, 0.9, 0.7]. keep-best must deliver attempt 1's
    # artifact (the 0.9), never the last (0.7). A keep-LAST bug passes every
    # monotonic test and fails only this one — the property the design rests on.
    save_json(project.root / "realm" / "calibration.json",
              {"research": {"gate": "armed", "theta": 0.99, "D": 1.0}})
    seq = iter([0.5, 0.9, 0.7])

    def fake_score(kind, brief, report, workspace, rubric, client=None):
        s = next(seq)
        return {"vector": {"s": s}, "weights": {"s": 1.0}, "scalar": s,
                "failing": ["s"], "critique": "scripted"}

    monkeypatch.setattr(fitness, "score", fake_score)

    class _Marked(Client):
        def __init__(self):
            self.n = -1

        def chat(self, messages, tools=None):
            text = " ".join((m.get("content") or "") for m in messages)
            if "This begins the round" in text:   # each attempt opens once
                self.n += 1
            return ChatResult(content=f"operator: this is attempt marker A{self.n}.")

    order = run_order(project, "research", "anything", echo=False, client=_Marked())
    assert order.state == "failed"                       # all three below θ=0.99
    failed = next(e for e in order.events if e["kind"] == "failed")
    assert failed["best_attempt"] == 1 and failed["best_score"] == 0.9
    kept = (order.dir / "report.md").read_text()
    assert "A1" in kept and "A2" not in kept             # the argmax, not the last
    assert kept == (order.dir / "attempts" / "1" / "report.md").read_text()


def test_armed_gate_fails_with_a_reason_not_a_graveyard(project):
    save_json(project.root / "realm" / "calibration.json",
              {"research": {"gate": "armed", "theta": 0.99, "D": 1.0}})

    class _AlwaysVague(Client):
        def chat(self, messages, tools=None):
            return ChatResult(content="a vague non-answer. operator: done.")

    order = run_order(project, "research", "a hard one, cite it", echo=False,
                      client=_AlwaysVague())
    assert order.state == "failed"
    failed = next(e for e in order.events if e["kind"] == "failed")
    assert "best_score" in failed and "critique" in failed and failed["best_attempt"] == 0
    # keep-best still left the best artifact on disk (a stop with a reason)
    assert (order.dir / "report.md").exists()
    assert OrderStore(project).load(order.id).state == "failed"
