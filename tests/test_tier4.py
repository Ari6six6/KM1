"""Tier 4 — the Frontier and the retrieval muscle, pinned.

Colonies: a sacrificial land on the internal dome (no egress, ever — fed
through the one gate). Territories: the structured record that survives the
raze. Recall: zero-dependency BM25 retrieval over everything the realm holds.
"""

from __future__ import annotations

import json

import pytest

from mor import recall, territory
from mor.engine import ToolContext
from mor.engine.dome import Dome
from mor.engine.tools import _frontier_exec, _recall


# --- the Frontier: colonies on the internal dome ------------------------------
def _fake_dome(space, monkeypatch, ps_names=()):
    import mor.engine.dome as dm
    calls = []

    def fake_sh(cmd, timeout=60):
        calls.append(cmd)
        if "version" in cmd:
            return 0, "Docker", ""
        if "ps " in cmd and "mor.colony" in cmd:
            return 0, "\n".join(ps_names), ""
        if "ps --filter name=" in cmd:
            return 0, "\n".join(ps_names), ""
        if " exec " in cmd:
            return 0, "ran it", ""
        return 0, "", ""

    monkeypatch.setattr(dm, "_sh", fake_sh)
    monkeypatch.setattr(dm, "probe_runtime", lambda: "docker")
    d = Dome(space)
    d.runtime = "docker"
    return d, calls


def test_a_colony_rises_internal_capped_and_egressless(space, monkeypatch):
    d, calls = _fake_dome(space, monkeypatch)
    ok, cname, msg = d.colonize("moises")
    assert ok and cname == "mor-test-frontier-moises"
    run = next(c for c in calls if " run -d " in c)
    assert "--network mor-test-dome" in run       # the internal dome — no egress
    assert "--cap-drop ALL" in run and "no-new-privileges" in run
    assert "-p " not in run                        # no published ports


def test_colonize_twice_stands_still(space, monkeypatch):
    d, calls = _fake_dome(space, monkeypatch,
                          ps_names=["mor-test-frontier-moises"])
    ok, _, msg = d.colonize("moises")
    assert ok and "already stands" in msg
    assert not any(" run -d " in c for c in calls)


def test_no_runtime_no_frontier(space, monkeypatch):
    monkeypatch.setattr("mor.engine.dome.probe_runtime", lambda: "")
    d = Dome(space)
    ok, _, msg = d.colonize("moises")
    assert not ok and "cannot be raised" in msg
    rc, _, err = d.frontier_exec("moises", "ls")
    assert rc == 127 and "no container runtime" in err


def test_frontier_exec_runs_and_logs_every_operation(space, monkeypatch):
    d, calls = _fake_dome(space, monkeypatch,
                          ps_names=["mor-test-frontier-moises"])
    rc, out, _ = d.frontier_exec("moises", "pytest -q")
    assert rc == 0 and out == "ran it"
    ops = (d.colony_dir("moises") / "ops.jsonl").read_text()
    rec = json.loads(ops.strip())
    assert rec["cmd"] == "pytest -q" and rec["rc"] == 0
    # an unknown colony is refused before any exec
    rc, _, err = d.frontier_exec("nowhere", "ls")
    assert rc == 127 and "no standing colony" in err


def test_colonies_and_raze(space, monkeypatch):
    d, calls = _fake_dome(space, monkeypatch,
                          ps_names=["mor-test-frontier-a", "mor-test-frontier-b"])
    assert d.colonies() == ["a", "b"]
    ok, msg = d.raze("a")
    assert ok and "raze" in msg and "record stay" in msg
    assert any("rm -f" in c and "frontier-a" in c for c in calls)


# --- the territory: the record that survives the raze -------------------------
def test_the_territory_book_opens_and_closes(space):
    territory.begin(space, "moises")
    rec = territory.load(space, "moises")
    assert rec["standing"] is True and rec["razed"] is None

    cdir = territory.colony_dir(space, "moises")
    (cdir / "src").mkdir(parents=True)
    (cdir / "src" / "main.py").write_text("def hello(): return 'world'\n")
    (cdir / "ops.jsonl").write_text(
        json.dumps({"ts": "t", "cmd": "python3 -m pytest", "rc": 0, "out": "1 passed"}) + "\n")
    rec = territory.harvest(space, "moises")
    assert rec["standing"] is False and rec["razed"]
    assert rec["counts"]["ops"] == 1 and rec["counts"]["files"] == 1
    assert rec["files"][0]["digest"].startswith("def hello")
    s = territory.summary(space, "moises")
    assert "razed" in s and "pytest" in s
    # the ground and the record both survive — raze is never erase
    assert cdir.is_dir() and "moises" in territory.all(space)


def test_binary_ground_is_listed_not_digested(space):
    cdir = territory.colony_dir(space, "binland")
    cdir.mkdir(parents=True)
    (cdir / "blob.bin").write_bytes(b"\x00\x01\x02" * 100)
    rec = territory.harvest(space, "binland")
    assert rec["files"][0]["bytes"] == 300 and "digest" not in rec["files"][0]


# --- recall: the retrieval muscle ----------------------------------------------
def test_the_right_passage_ranks_first():
    docs = [
        ("walls/general", "strategy is the art of the long game and patience"),
        ("skills/serve-glm", "always tunnel port 18080 before serving the model"),
        ("chants/day-1", "the seer dreamed and the general weighed the wire"),
    ]
    hits = recall.retrieve("which port do I tunnel before serving", docs, k=2)
    assert hits and hits[0][0] == "skills/serve-glm"
    assert "18080" in hits[0][1]


def test_empty_query_and_empty_ground():
    assert recall.retrieve("", [("a", "text")]) == []
    assert recall.retrieve("anything", []) == []


def test_workspace_corpus_skips_binary(space, tmp_path):
    (tmp_path / "code.py").write_text("def retrieve_the_matrix(): pass\n")
    (tmp_path / "blob.bin").write_bytes(b"\x00\xff" * 50)
    docs = recall.load_corpus(space, "workspace", workspace=tmp_path)
    refs = [r for r, _ in docs]
    assert any("code.py" in r for r in refs)
    assert not any("blob.bin" in r for r in refs)


def test_source_filtering_and_territory_corpus(space, tmp_path):
    from mor import skills
    skills.record(space, "tunneling", "# Tunneling\nPort 18080 first, always.")
    territory.begin(space, "moises")
    only_skills = recall.load_corpus(space, "skills", workspace=tmp_path)
    assert all(r.startswith("skills/") for r, _ in only_skills)
    terr = recall.load_corpus(space, "territories", workspace=tmp_path)
    assert any(r.startswith("territory/moises") for r, _ in terr)


# --- the tools the faces hold ---------------------------------------------------
def test_recall_tool_answers_from_the_ground(space, tmp_path):
    (tmp_path / "notes.md").write_text("the warrior always checks the gate first\n")
    ctx = ToolContext(workspace=tmp_path, space=space, can_egress=False,
                      tainted=[], role="wizard")
    out = _recall({"query": "who checks the gate"}, ctx)
    assert "notes.md" in out and "checks the gate" in out
    assert "nothing in" in _recall({"query": "zzzzz qqqqq"}, ctx)


def test_frontier_exec_tool_serves_the_seventh(space, tmp_path):
    from types import SimpleNamespace
    dome = SimpleNamespace(
        frontier_exec=lambda name, cmd: (0, "all green", ""))
    ctx = ToolContext(workspace=tmp_path, space=space, can_egress=False,
                      tainted=[], dome=dome, role="warrior")
    out = _frontier_exec({"colony": "moises", "command": "pytest"}, ctx)
    assert "all green" in out and ctx.checked is True
    # a refused exec is NOT a check
    ctx2 = ToolContext(workspace=tmp_path, space=space, can_egress=False,
                       tainted=[], dome=SimpleNamespace(
                           frontier_exec=lambda n, c: (127, "", "no standing colony 'x'")),
                       role="warrior")
    out2 = _frontier_exec({"colony": "x", "command": "ls"}, ctx2)
    assert out2.startswith("ERROR") and ctx2.checked is False


# --- the command line ------------------------------------------------------------
def test_colonize_and_territory_commands(space, monkeypatch, capsys):
    from mor.cli import _dispatch
    from mor.realm import Realm
    monkeypatch.setattr("mor.engine.dome.probe_runtime", lambda: "")
    r = Realm(space, echo=False)
    assert _dispatch(r, "colonize moises") is True
    assert "cannot be raised" in capsys.readouterr().out
    assert _dispatch(r, "territory moises") is True
    assert "no territory" in capsys.readouterr().out
    assert _dispatch(r, "colonies") is True
    assert "quiet" in capsys.readouterr().out
