"""The Eleventh Evangelism, proven: the Audit (falsification state in the
loop), rung escalation by evidence, and the centrality lantern."""

from __future__ import annotations

import json

from mor import grimoire, juice, source
from mor.engine import ScriptBackend, ToolContext, default_tools, think_and_act
from mor.engine.tools import execute


class CaptureBackend(ScriptBackend):
    """A scripted oracle that remembers everything it was shown."""
    def __init__(self, script):
        super().__init__(script)
        self.seen = []

    def chat(self, messages, tools=None):
        self.seen.append(" || ".join(str(m.get("content", "")) for m in messages))
        return super().chat(messages, tools)


def _ctx(space, **kw):
    base = dict(workspace=space.root / "w", space=space, role="warrior")
    base.update(kw)
    return ToolContext(**base)


def _search_call(pattern="gate"):
    return {"tool": "search_workspace", "args": {"pattern": pattern}}


class TestAudit:
    def test_working_turn_is_audited_once(self, space):
        backend = CaptureBackend([
            _search_call(),
            {"text": "the gate allows one hop only"},
            {"text": "I attacked it — it held"},
        ])
        ctx = _ctx(space, falsify=True)
        tools = default_tools(ctx)
        spoken, _ = think_and_act(backend, role="warrior", kind="council_from_general",
                                  heard="", system="s", user="u", tools=tools, ctx=ctx)
        assert spoken == "I attacked it — it held"
        nudges = [s for s in backend.seen if "proving it WRONG" in s]
        assert len(nudges) == 1  # exactly one audit, never a loop of audits

    def test_no_audit_without_the_flag(self, space):
        backend = CaptureBackend([_search_call(), {"text": "plain conclusion"}])
        ctx = _ctx(space)  # falsify defaults False
        tools = default_tools(ctx)
        spoken, _ = think_and_act(backend, role="warrior", kind="wake",
                                  heard="", system="s", user="u", tools=tools, ctx=ctx)
        assert spoken == "plain conclusion"

    def test_no_audit_when_nothing_was_done(self, space):
        backend = CaptureBackend([{"text": "just a greeting"}])
        ctx = _ctx(space, falsify=True)
        spoken, _ = think_and_act(backend, role="wizard", kind="council_from_general",
                                  heard="", system="s", user="u",
                                  tools=default_tools(ctx), ctx=ctx)
        assert spoken == "just a greeting"
        assert not any("proving it WRONG" in s for s in backend.seen)

    def test_audit_names_the_weakest_claim(self, space):
        grimoire.record_claim(space, "gate", "the gate is one hop",
                              rung="inferred")
        backend = CaptureBackend([
            _search_call(),
            {"text": "conclusion"},
            {"text": "attacked"}])
        ctx = _ctx(space, falsify=True)
        think_and_act(backend, role="warrior", kind="council_from_general",
                      heard="", system="s", user="u",
                      tools=default_tools(ctx), ctx=ctx)
        assert any("the gate is one hop" in s for s in backend.seen)

    def test_audit_extends_the_leash(self, space):
        backend = CaptureBackend([
            _search_call(),
            {"text": "conclusion"},
            {"text": "after the audit"}])
        ctx = _ctx(space, falsify=True)
        spoken, _ = think_and_act(backend, role="warrior", kind="council_from_general",
                                  heard="", system="s", user="u",
                                  tools=default_tools(ctx), ctx=ctx, max_steps=3)
        # step 0 acted, step 1 was bounced into the audit (budget grew), step 2 spoke
        assert spoken == "after the audit"
        assert len(backend.seen) == 3


class TestRungEscalation:
    def test_checked_turn_floors_the_rung(self, space):
        cid = grimoire.record_claim(space, "s", "a claim", rung="inferred")
        ctx = _ctx(space)
        ctx.checked = True  # a real check ran this turn
        tools = default_tools(ctx)
        call = type("C", (), {"name": "grimoire_mark", "arguments": json.dumps(
            {"subject": "s", "claim_id": cid, "status": "held"})})
        out = execute(tools, call, ctx)
        assert "computed" in out
        claim = grimoire.load(space)["subjects"]["s"]["claims"][cid]
        assert claim["rung"] == "computed"

    def test_unchecked_turn_keeps_the_declared_rung(self, space):
        cid = grimoire.record_claim(space, "s", "a claim", rung="inferred")
        ctx = _ctx(space)
        tools = default_tools(ctx)
        call = type("C", (), {"name": "grimoire_mark", "arguments": json.dumps(
            {"subject": "s", "claim_id": cid, "status": "held"})})
        execute(tools, call, ctx)
        claim = grimoire.load(space)["subjects"]["s"]["claims"][cid]
        assert claim["rung"] == "inferred"


class TestCentralityLantern:
    def test_warrior_sortie_task_carries_topology(self, space):
        from mor import territory
        from mor.agents import _council_task
        cdir = territory.colony_dir(space, "study-land")
        (cdir / "src").mkdir(parents=True)
        (cdir / "src" / "core.py").write_text("import helper\n")
        (cdir / "src" / "helper.py").write_text("X = 1\n")

        class FakeDome:
            def colonies(self):
                return ["study-land"]
        space.dome = FakeDome()
        task = _council_task(space, "warrior", "general", "go study the colony")
        assert "most load-bearing" in task and "helper" in task

    def test_smiths_night_carries_the_realms_own_topology(self, space, tmp_path,
                                                          monkeypatch):
        root = tmp_path
        (root / "mor").mkdir()
        (root / "mor" / "core.py").write_text("import helper\n")
        (root / "mor" / "helper.py").write_text("X = 1\n")
        (root / "tests").mkdir()
        (root / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
        monkeypatch.setattr(source, "source_root", lambda: root)
        backend = CaptureBackend([{"text": "nothing worth changing tonight"}])
        juice.improve_cycle(space, backend, brief="look around")
        assert any("topology" in s for s in backend.seen)
