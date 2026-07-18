"""The Tenth Evangelism, proven: the Forge (source scope + git + the suite as
oracle), the tools.d forge, and the Ontology (graph + hybrid retrieval)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mor import forge, juice, ontology, source
from mor.engine import MockBackend, ScriptBackend, ToolContext, default_tools
from mor.engine.tools import execute


# ------------------------------------------------------------------- source
class TestSource:
    def test_read_self(self):
        out = source.read("mor/source.py")
        assert "The Tenth Evangelism" in out

    def test_read_missing(self):
        assert "ERROR" in source.read("mor/nope.py")

    def test_list_root(self):
        out = source.list_dir(".")
        assert "mor/" in out and "tests/" in out

    def test_search_finds(self):
        out = source.search("def source_root", "mor")
        assert "source.py" in out

    def test_escape_refused(self):
        with pytest.raises(ValueError):
            source._safe("../../etc/passwd")

    def test_write_guards(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "source_root", lambda: tmp_path)
        assert "ERROR" in source.write("evil.sh", "echo hi")       # bad suffix
        assert "ERROR" in source.write(".hidden/x.py", "x = 1")    # hidden path
        assert "ERROR" in source.write("ok.py", "   ")             # empty
        assert "ERROR" in source.write("../ok.py", "x = 1")        # escape

    def test_write_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "source_root", lambda: tmp_path)
        assert "forged" in source.write("pkg/mod.py", "X = 1\n")
        assert source.read("pkg/mod.py") == "X = 1\n"
        assert "rewrote" in source.write("pkg/mod.py", "X = 2\n")


# -------------------------------------------------------------------- forge
GOOD_TOOL = '''
NAME = "shout"
DESCRIPTION = "Say it loudly."
PARAMETERS = {"type": "object", "properties": {"text": {"type": "string"}},
              "required": ["text"]}
def run(args, ctx):
    return (args.get("text") or "").upper() + "!"
'''


class TestForge:
    def _ctx(self, space):
        return ToolContext(workspace=space.root / "w", space=space, role="wizard")

    def test_forge_and_load(self, space):
        assert forge.forge(space, "shout", GOOD_TOOL) == ""
        tools = default_tools(self._ctx(space))
        t = next(t for t in tools if t.name == "shout")
        call = type("C", (), {"name": "shout",
                              "arguments": json.dumps({"text": "juice"})})
        assert execute(tools, call, self._ctx(space)) == "JUICE!"

    def test_broken_module_refused_and_removed(self, space):
        err = forge.forge(space, "broken", "def nope(:\n")
        assert "did not import" in err
        assert not (forge.tools_dir(space) / "broken.py").exists()

    def test_contract_refused(self, space):
        err = forge.forge(space, "nope", "NAME = 'nope'\n")
        assert "contract" in err
        assert not (forge.tools_dir(space) / "nope.py").exists()

    def test_name_mismatch_refused(self, space):
        err = forge.forge(space, "file_name", GOOD_TOOL)  # NAME says 'shout'
        assert "must match" in err

    def test_forged_tool_failure_is_an_observation_not_a_crash(self, space):
        bad = GOOD_TOOL.replace("return", "raise RuntimeError('boom')\n    return")
        assert forge.forge(space, "shout", bad) == ""
        tools = default_tools(self._ctx(space))
        call = type("C", (), {"name": "shout", "arguments": "{}"})
        assert "ERROR in forged tool" in execute(tools, call, self._ctx(space))

    def test_list_forged(self, space):
        forge.forge(space, "shout", GOOD_TOOL)
        rows = dict(forge.list_forged(space))
        assert rows["shout"] == "forged and standing"


# ----------------------------------------------------------------- ontology
class TestOntology:
    def test_relate_idempotent_strengthens(self, space):
        conn = ontology.connect(space)
        ontology.relate(conn, "MoR", "uses", "sqlite")
        ontology.relate(conn, "MoR", "uses", "sqlite")
        w = conn.execute("SELECT weight FROM triples WHERE subject='MoR'").fetchone()[0]
        assert w == 1.5
        assert ontology.stats(conn)["entities"] == 2
        conn.close()

    def test_ingest_idempotent(self, space):
        conn = ontology.connect(space)
        text = "The Warrior guards the gate. " * 30
        n1 = ontology.ingest_text(conn, "chants", "day-1.md", text)
        n2 = ontology.ingest_text(conn, "chants", "day-1.md", text)
        assert n1 > 0 and n2 == 0
        conn.close()

    def test_ask_returns_passages_and_triples(self, space):
        conn = ontology.connect(space)
        ontology.ingest_text(conn, "walls", "wizard.md",
                             "The Wizard keeps the Theory of the World and "
                             "writes the Chant at dusk. " * 8)
        ontology.relate(conn, "Wizard", "writes", "Chant")
        out = ontology.ask(conn, "who writes the Chant?", k=3)
        assert out["how"] == "hashed"           # no mind attached → honest fallback
        assert any("Chant" in p["excerpt"] for p in out["passages"])
        assert any(t["p"] == "writes" for t in out["triples"])
        conn.close()

    def test_query_finds_facts_with_no_passages_at_all(self, space):
        conn = ontology.connect(space)
        ontology.relate(conn, "Realm", "uses", "Vast.ai")
        out = ontology.ask(conn, "what does the realm use?")
        assert any(t["s"] == "Realm" for t in out["triples"])
        conn.close()

    def test_extractor_warms_graph(self, space):
        conn = ontology.connect(space)
        ontology.extract_and_relate(conn, "Vast.ai is a GPU rental market. "
                                          "The Realm uses Vast.ai nightly.")
        names = {r[0] for r in conn.execute("SELECT name FROM entities")}
        assert "Vast.ai" in names
        conn.close()

    def test_hashed_vectors_deterministic(self):
        a1, _ = ontology.embed(["the gate stays shut"], None)
        a2, _ = ontology.embed(["the gate stays shut"], None)
        b, _ = ontology.embed(["an entirely different sentence altogether"], None)
        assert a1 == a2
        same = ontology._cos(a1[0], a2[0])
        diff = ontology._cos(a1[0], b[0])
        assert same > 0.99 and diff < 0.5

    def test_mock_backend_has_no_embeddings(self):
        assert MockBackend().embed(["x"]) is None


# ------------------------------------------------------- graph tools (faces)
class TestGraphTools:
    def test_ask_graph_and_relate_through_the_loop(self, space):
        (space.root / "chants").mkdir(parents=True, exist_ok=True)
        (space.root / "chants" / "day-0001.md").write_text(
            "The seer dreamed of a gate that only opens one hop. " * 10)
        ctx = ToolContext(workspace=space.root / "w", space=space, role="wizard")
        tools = default_tools(ctx)
        rel = type("C", (), {"name": "relate", "arguments": json.dumps(
            {"subject": "Gate", "predicate": "allows", "object": "one hop"})})
        assert "Gate" in execute(tools, rel, ctx)
        ask = type("C", (), {"name": "ask_graph", "arguments": json.dumps(
            {"query": "how many hops does the gate allow?"})})
        out = execute(tools, ask, ctx)
        assert "one hop" in out


# ------------------------------------------------------------- juice (git)
def _mini_repo(tmp_path) -> Path:
    """A tiny standalone 'realm' the suite-oracle can judge without recursion."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "core.py").write_text("X = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text(
        "def test_x():\n    assert 1 == 1\n")
    return tmp_path


class TestJuiceGit:
    def test_ensure_repo_commit_revert(self, tmp_path):
        root = _mini_repo(tmp_path)
        assert juice.ensure_repo(root)
        assert juice.git_ready(root)
        (root / "pkg" / "core.py").write_text("X = 2\n")
        rev = juice._commit(root, "change X")
        assert rev
        (root / "pkg" / "core.py").write_text("X = 3\n")
        (root / "pkg" / "stray.py").write_text("S = 1\n")
        juice._revert(root)
        assert (root / "pkg" / "core.py").read_text() == "X = 2\n"
        assert not (root / "pkg" / "stray.py").exists()

    def test_run_suite_green_and_red(self, tmp_path):
        root = _mini_repo(tmp_path)
        out = juice.run_suite(root)
        assert out["ok"] and out["passed"] == 1
        (root / "tests" / "test_core.py").write_text(
            "def test_x():\n    assert False\n")
        out = juice.run_suite(root)
        assert not out["ok"] and out["failed"] == 1


class TestImproveCycle:
    def test_offline_refuses_honestly(self, space):
        rec = juice.improve_cycle(space, MockBackend(), brief="anything")
        assert rec["kept"] is False and rec["reason"] == "offline"

    def test_green_change_is_kept_and_committed(self, space, tmp_path,
                                                monkeypatch):
        root = _mini_repo(tmp_path)
        monkeypatch.setattr(source, "source_root", lambda: root)
        script = [
            {"tool": "source_write",
             "args": {"path": "pkg/note.py", "content": "NOTE = 'juice'\n"}},
            {"text": "I forged a note module; the suite should stay green."},
        ]
        rec = juice.improve_cycle(space, ScriptBackend(script), brief="add a note")
        assert rec["kept"] is True, rec
        assert (root / "pkg" / "note.py").exists()
        log = subprocess.run(["git", "log", "--oneline"], cwd=str(root),
                             capture_output=True, text=True).stdout
        assert "forge:" in log
        attempts = juice.past_attempts(space)
        assert attempts and attempts[-1]["kept"] is True

    def test_red_change_is_reverted(self, space, tmp_path, monkeypatch):
        root = _mini_repo(tmp_path)
        monkeypatch.setattr(source, "source_root", lambda: root)
        script = [
            {"tool": "source_write",
             "args": {"path": "tests/test_core.py",
                      "content": "def test_x():\n    assert False\n"}},
            {"text": "I broke the suite to prove the rail."},
        ]
        rec = juice.improve_cycle(space, ScriptBackend(script), brief="sabotage")
        assert rec["kept"] is False and rec["reason"] == "suite-red"
        assert "assert 1 == 1" in (root / "tests" / "test_core.py").read_text()

    def test_no_change_is_logged_not_kept(self, space, tmp_path, monkeypatch):
        root = _mini_repo(tmp_path)
        monkeypatch.setattr(source, "source_root", lambda: root)
        script = [{"text": "Nothing tonight was worth changing."}]
        rec = juice.improve_cycle(space, ScriptBackend(script), brief="")
        assert rec["kept"] is False and rec["reason"] == "no-change"
        assert juice.past_attempts(space)[-1]["reason"] == "no-change"
