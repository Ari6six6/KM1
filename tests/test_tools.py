"""The tools and their rails — files sandboxed, egress gated and SSRF-guarded.

Runs with no model, no network (the SSRF checks never actually connect).
"""

from __future__ import annotations

import pytest

from mor.tools import (_resolve_public, _safe, _search, _read_file, _web_fetch,
                       ToolContext, build_tools, execute)
from mor.llm import ToolCall


def _ctx(project, can_egress=False, shell_mode="off"):
    ws = project.workspace
    ws.mkdir(parents=True, exist_ok=True)
    return ToolContext(workspace=ws, project=project, can_egress=can_egress,
                       shell_mode=shell_mode)


# --- file sandbox ----------------------------------------------------------
def test_path_escape_is_refused(project):
    ctx = _ctx(project)
    with pytest.raises(ValueError):
        _safe(ctx, "../../etc/passwd")


def test_read_file_pages_without_dropping(project):
    ctx = _ctx(project)
    body = "".join(f"line {i}\n" for i in range(3000))
    (ctx.workspace / "big.txt").write_text(body)
    first = _read_file({"path": "big.txt"}, ctx)
    assert "TRUNCATED" in first
    # page through every window; nothing is dropped
    collected, offset = "", 0
    while True:
        chunk = _read_file({"path": "big.txt", "offset": offset}, ctx)
        if "TRUNCATED" in chunk:
            body_part, _, _ = chunk.partition("\n\n[TRUNCATED")
            collected += body_part
            offset = int(chunk.split("offset=")[1].split(" ")[0])
        else:
            collected += chunk
            break
    assert "line 0\n" in collected and "line 2999" in collected


def test_search_finds_matches(project):
    ctx = _ctx(project)
    (ctx.workspace / "a.py").write_text("def target():\n    return 1\n")
    out = _search({"pattern": r"def target"}, ctx)
    assert "a.py:1" in out


# --- egress rails ----------------------------------------------------------
def test_web_fetch_denied_without_egress_permission(project):
    ctx = _ctx(project, can_egress=False)
    project.allow("example.com")
    assert _web_fetch({"url": "https://example.com"}, ctx).startswith("DENIED")


def test_web_fetch_denied_when_domain_not_allowed(project):
    ctx = _ctx(project, can_egress=True)
    out = _web_fetch({"url": "https://example.com"}, ctx)
    assert "DENIED" in out and "closed" in out


def test_ssrf_guard_blocks_loopback():
    # localhost must resolve to a non-public address and be refused.
    _ips, reason = _resolve_public("localhost")
    assert reason and "non-public" in reason


def test_web_fetch_blocks_private_even_when_allowed(project):
    ctx = _ctx(project, can_egress=True)
    project.allow("localhost")   # even explicitly allowed…
    out = _web_fetch({"url": "http://localhost:80"}, ctx)
    assert out.startswith("DENIED") and "private" in out  # …the SSRF rail still refuses


# --- shell gating ----------------------------------------------------------
def test_shell_off_by_default(project):
    ctx = _ctx(project, shell_mode="off")
    tools = build_tools(["run_shell"], ctx)
    out = execute(tools, ToolCall("c", "run_shell", '{"command": "echo hi"}'), ctx)
    assert out.startswith("DENIED")


def test_host_shell_runs_when_explicitly_enabled(project):
    ctx = _ctx(project, shell_mode="host")
    tools = build_tools(["run_shell"], ctx)
    out = execute(tools, ToolCall("c", "run_shell", '{"command": "echo hello"}'), ctx)
    assert "hello" in out and "exit 0" in out


def test_container_shell_degrades_cleanly_without_runtime(project, monkeypatch):
    # with no usable container runtime, the sandboxed shell refuses rather than
    # silently falling back to the host.
    monkeypatch.setattr("mor.sandbox.probe_runtime", lambda: "")
    ctx = _ctx(project, shell_mode="container")
    tools = build_tools(["run_shell"], ctx)
    out = execute(tools, ToolCall("c", "run_shell", '{"command": "echo hi"}'), ctx)
    assert out.startswith("DENIED") and "runtime" in out


def test_container_shell_uses_the_runtime_when_present(project, monkeypatch):
    calls = {}

    def fake_run(workspace, command, *, runtime, network, timeout=120):
        calls.update(workspace=workspace, command=command, runtime=runtime,
                     network=network)
        return 0, "sandboxed-hello\n", ""

    monkeypatch.setattr("mor.sandbox.probe_runtime", lambda: "docker")
    monkeypatch.setattr("mor.sandbox.run_in_container", fake_run)
    ctx = _ctx(project, shell_mode="container")
    ctx.shell_net = "none"
    tools = build_tools(["run_shell"], ctx)
    out = execute(tools, ToolCall("c", "run_shell", '{"command": "echo hi"}'), ctx)
    assert "sandboxed-hello" in out and calls["runtime"] == "docker"
    assert calls["network"] == "none"


# --- build_tools filtering -------------------------------------------------
def test_build_tools_drops_web_fetch_without_egress(project):
    ctx = _ctx(project, can_egress=False)
    names = [t.name for t in build_tools(["read_file", "web_fetch"], ctx)]
    assert "web_fetch" not in names and "read_file" in names


def test_remember_persists_a_note(project):
    ctx = _ctx(project)
    tools = build_tools(["remember"], ctx)
    execute(tools, ToolCall("c", "remember", '{"note": "the east ford is out"}'), ctx)
    assert "east ford" in project.notes()
