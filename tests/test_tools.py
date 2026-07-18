"""The tools and their rails — files sandboxed, egress gated and SSRF-guarded.

Runs with no model, no network (the SSRF checks never actually connect).
"""

from __future__ import annotations

import pytest

from mor.tools import (_resolve_public, _safe, _search, _read_file, _web_fetch,
                       ToolContext, build_tools, execute)
from mor.llm import ToolCall


def _ctx(project, can_egress=False, allow_shell=False):
    ws = project.workspace
    ws.mkdir(parents=True, exist_ok=True)
    return ToolContext(workspace=ws, project=project, can_egress=can_egress,
                       allow_shell=allow_shell)


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
    ctx = _ctx(project, allow_shell=False)
    tools = build_tools(["run_shell"], ctx)
    out = execute(tools, ToolCall("c", "run_shell", '{"command": "echo hi"}'), ctx)
    assert out.startswith("DENIED")


def test_shell_runs_when_enabled(project):
    ctx = _ctx(project, allow_shell=True)
    tools = build_tools(["run_shell"], ctx)
    out = execute(tools, ToolCall("c", "run_shell", '{"command": "echo hello"}'), ctx)
    assert "hello" in out and "exit 0" in out


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
