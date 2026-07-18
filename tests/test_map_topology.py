"""The topological radar — import-centrality drawn by regex, no parser, no deps."""

from __future__ import annotations

from mor import map_topology


def test_centrality_ranks_the_most_imported_module_first(tmp_path):
    # a small tree: core is imported by two others; leaf imports nothing local
    (tmp_path / "core.py").write_text("x = 1\n")
    (tmp_path / "a.py").write_text("from core import x\n")
    (tmp_path / "b.py").write_text("import core\n")
    (tmp_path / "leaf.py").write_text("import os\n")  # stdlib, not a local edge

    deg = map_topology.scan(tmp_path)
    assert deg["core"]["in"] == 2      # a and b lean on it
    assert deg["a"]["out"] == 1 and deg["b"]["out"] == 1
    assert deg["leaf"]["in"] == 0 and deg["leaf"]["out"] == 0  # os isn't local

    summary = map_topology.summary(tmp_path)
    assert summary.startswith("topology, most load-bearing first: core")


def test_empty_tree_says_so(tmp_path):
    assert "no Python modules" in map_topology.summary(tmp_path)


def test_map_workspace_tool_is_available_and_runs(space):
    from mor.engine import ToolContext, default_tools
    from mor.engine.backend import ToolCall
    from mor.engine.tools import execute
    ws = space.root / "population" / "wizard" / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "hub.py").write_text("v = 1\n")
    (ws / "user.py").write_text("import hub\n")
    ctx = ToolContext(workspace=ws, space=space, role="wizard")
    assert "map_workspace" in [t.name for t in default_tools(ctx)]
    out = execute(default_tools(ctx), ToolCall("c", "map_workspace", "{}"), ctx)
    assert "hub" in out and "imported by 1" in out
