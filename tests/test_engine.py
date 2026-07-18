"""The suite that should have existed — it drives the engine and pins the two rails.

Runs with no GPU, no Docker, no network (faked where needed). `pytest -q`.
"""

from __future__ import annotations

import os

import pytest

from mor.engine import (Dome, MockBackend, ScriptBackend, ToolContext,
                        default_tools, hall_view, think_and_act)
from mor.engine.backend import Backend, ChatResult, ToolCall
from mor.engine.loop import _BUDGET_NUDGE, _REFLECT_NUDGE
from mor.engine.tools import (_blocked_ip, _read_file, _safe, _search_workspace,
                              _web_fetch, execute)


def _ctx(space, role="warrior", can_egress=True):
    ws = space.root / "population" / role / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ToolContext(workspace=ws, space=space, can_egress=can_egress,
                       tainted=[], role=role)


# --- the loop --------------------------------------------------------------
def test_loop_executes_a_tool_and_grounds_its_answer(space):
    ctx = _ctx(space, role="wizard", can_egress=False)
    (ctx.workspace / "note.txt").write_text("the east ford is out")
    backend = ScriptBackend([
        {"tool": "read_file", "args": {"path": "note.txt"}},
        {"text": "The east ford is out; we route north."},
    ])
    line, tainted = think_and_act(
        backend, role="wizard", kind="wake", heard="", system="You are the Wizard.",
        user="read note.txt", tools=default_tools(ctx), ctx=ctx)
    assert "north" in line
    assert tainted is False


def test_offline_mind_runs_the_loop_in_character(space):
    ctx = _ctx(space, role="general", can_egress=False)
    line, _ = think_and_act(
        MockBackend(), role="general", kind="wake", heard="", system="s", user="u",
        tools=default_tools(ctx), ctx=ctx)
    assert "offline mind heard" not in line  # seeded flavor, not the raw echo
    assert line.strip()


def test_reflect_reflex_pushes_to_think_after_acting_without_reasoning(space):
    ctx = _ctx(space, role="wizard", can_egress=False)
    (ctx.workspace / "f").write_text("x")

    class Capture(Backend):
        def __init__(self):
            self.last = []

        def chat(self, messages, tools=None):
            self.last = list(messages)
            # act (no content) three times, then finish
            acted = sum(1 for m in messages if m.get("role") == "tool")
            if acted < 3:
                return ChatResult(content=None,
                                  tool_calls=[ToolCall("c", "read_file", '{"path": "f"}')])
            return ChatResult(content="done")

    b = Capture()
    think_and_act(b, role="wizard", kind="wake", heard="", system="s", user="u",
                  tools=default_tools(ctx), ctx=ctx)
    assert any(m.get("content") == _REFLECT_NUDGE for m in b.last)


# --- sortie tooling: paginated reads, workspace search, the budget valve ----
def test_read_file_pages_a_long_file_without_dropping_any(space):
    ctx = _ctx(space, role="wizard", can_egress=False)
    body = "".join(f"line {i}\n" for i in range(3000))  # well past one 8k window
    (ctx.workspace / "big.txt").write_text(body)

    first = _read_file({"path": "big.txt"}, ctx)
    assert "[TRUNCATED:" in first and "offset=8000" in first
    # follow the notice — the second window continues exactly where the first ended
    second = _read_file({"path": "big.txt", "offset": 8000}, ctx)
    assert body[8000:8000 + 20] in second
    # a small file is returned whole, with no notice at all
    (ctx.workspace / "small.txt").write_text("just a little")
    assert _read_file({"path": "small.txt"}, ctx) == "just a little"


def test_search_workspace_finds_matches_with_locations(space):
    ctx = _ctx(space, role="wizard", can_egress=False)
    (ctx.workspace / "a.py").write_text("def foo():\n    return 1\n")
    (ctx.workspace / "b.py").write_text("x = foo()\n")
    out = _search_workspace({"pattern": r"foo"}, ctx)
    assert "a.py:1:" in out and "b.py:1:" in out


def test_search_workspace_caps_and_reports_it(space):
    ctx = _ctx(space, role="wizard", can_egress=False)
    (ctx.workspace / "many.txt").write_text("hit\n" * 200)
    out = _search_workspace({"pattern": "hit"}, ctx)
    assert out.count("many.txt:") == 50 and "capped at 50" in out


def test_search_workspace_rejects_bad_regex(space):
    ctx = _ctx(space, role="wizard", can_egress=False)
    assert _search_workspace({"pattern": "("}, ctx).startswith("ERROR: bad regex")


def test_search_workspace_path_escape_is_blocked(space):
    ctx = _ctx(space, role="wizard", can_egress=False)
    out = execute(default_tools(ctx),
                  ToolCall("c", "search_workspace",
                           '{"pattern": "x", "path": "../../etc"}'), ctx)
    assert out.startswith("ERROR")


def test_budget_valve_fires_once_with_two_steps_left(space):
    """On a long leash, the loop warns the face once when two steps remain — so it
    lands its answer instead of being cut off cold."""
    ctx = _ctx(space, role="warrior", can_egress=False)
    (ctx.workspace / "f").write_text("x")

    class AlwaysActs(Backend):
        def __init__(self):
            self.seen = []

        def chat(self, messages, tools=None):
            self.seen = list(messages)
            return ChatResult(content="working",
                              tool_calls=[ToolCall("c", "read_file", '{"path": "f"}')])

    b = AlwaysActs()
    think_and_act(b, role="warrior", kind="council_from_general", heard="", system="s",
                  user="u", tools=default_tools(ctx), ctx=ctx, max_steps=4)
    assert sum(1 for m in b.seen if m.get("content") == _BUDGET_NUDGE) == 1


# --- the gate (finding #1) -------------------------------------------------
def test_non_warrior_cannot_egress(space):
    ctx = _ctx(space, role="wizard", can_egress=False)
    space.authorize("*")
    assert "web_fetch" not in [t.name for t in default_tools(ctx)]
    assert _web_fetch({"url": "https://example.com"}, ctx).startswith("DENIED")


def test_gate_shut_refuses(space):
    ctx = _ctx(space)
    assert _web_fetch({"url": "https://example.com"}, ctx).startswith("DENIED: the gate")


def test_run_shell_absent_and_air_gapped_when_disembodied(space):
    ctx = _ctx(space)  # no dome attached
    # With no body, the shell isn't even offered as a tool...
    assert "run_shell" not in [t.name for t in default_tools(ctx)]
    # ...and calling it directly refuses (it only runs inside an air-gapped body).
    from mor.engine.tools import _run_shell
    assert "no body" in _run_shell({"command": "curl http://x"}, ctx)


# --- the SSRF rail (finding #2) --------------------------------------------
@pytest.mark.parametrize("addr", ["127.0.0.1", "169.254.169.254", "10.0.0.5",
                                  "192.168.1.1", "::1"])
def test_ssrf_blocks_non_public(space, monkeypatch, addr):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", (addr, 0))])
    ctx = _ctx(space)
    space.authorize("*")
    assert _web_fetch({"url": "http://totally-public.example/"}, ctx).startswith("DENIED")


def test_bad_scheme_refused(space):
    ctx = _ctx(space)
    space.authorize("*")
    assert _web_fetch({"url": "file:///etc/passwd"}, ctx).startswith("DENIED")


class FakeResp:
    status = 200

    def read(self, n=None):
        return b"<html>outside</html>"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _resolve_public(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])


def test_public_fetch_taints_and_maps(space, monkeypatch):
    _resolve_public(monkeypatch)
    monkeypatch.setattr("mor.engine.tools._open_one_hop", lambda *a, **k: FakeResp())
    ctx = _ctx(space)
    space.authorize("example.com")
    out = _web_fetch({"url": "http://example.com/"}, ctx)
    assert "TAINTED" in out
    assert ctx.tainted == ["example.com"]
    from mor import world
    assert "example.com" in world.load(space).get("places", {})


# --- the gate takes one hop (finding #6) ------------------------------------
def _http_error(url, code, msg, location=None, body=b""):
    import email.message
    import io
    import urllib.error
    headers = email.message.Message()
    if location:
        headers["Location"] = location
    return urllib.error.HTTPError(url, code, msg, headers, io.BytesIO(body))


def test_redirect_is_refused_not_followed(space, monkeypatch):
    """An authorized site 302-ing to the metadata endpoint (or anywhere) is the
    classic pivot past both rails — the gate must refuse the hop, not take it."""
    _resolve_public(monkeypatch)
    evil = "http://169.254.169.254/latest/meta-data/"

    def bounce(req, timeout):
        raise _http_error(req.full_url, 302, "Found", location=evil)

    monkeypatch.setattr("mor.engine.tools._open_one_hop", bounce)
    ctx = _ctx(space)
    space.authorize("example.com")
    out = _web_fetch({"url": "http://example.com/"}, ctx)
    assert out.startswith("DENIED")
    assert evil in out              # the destination is reported, not visited
    assert ctx.tainted == []        # nothing crossed, nothing to taint


def test_http_error_body_is_still_tainted_outside_data(space, monkeypatch):
    """A 404 page is still an answer from outside — deliver it under the taint
    flag instead of swallowing it as an opaque ERROR."""
    _resolve_public(monkeypatch)

    def not_found(req, timeout):
        raise _http_error(req.full_url, 404, "Not Found", body=b"no such page")

    monkeypatch.setattr("mor.engine.tools._open_one_hop", not_found)
    ctx = _ctx(space)
    space.authorize("example.com")
    out = _web_fetch({"url": "http://example.com/gone"}, ctx)
    assert out.startswith("[404]") and "TAINTED" in out and "no such page" in out
    assert ctx.tainted == ["example.com"]


# --- path safety -----------------------------------------------------------
def test_path_escape_is_blocked(space):
    ctx = _ctx(space)
    with pytest.raises(ValueError):
        _safe(ctx, "../../etc/passwd")
    out = execute(default_tools(ctx),
                  ToolCall("c", "read_file", '{"path": "../../etc/passwd"}'), ctx)
    assert out.startswith("ERROR")


# --- compaction ------------------------------------------------------------
def test_hall_folds_when_long(space):
    from mor.hall import Hall
    h = Hall(space, 1, echo=False)
    for i in range(6):
        h.post("general", "wizard", f"line {i}")
    assert "folded" not in hall_view(h, MockBackend())
    for i in range(50):
        h.post("wizard", "general", f"detail {i}")
    view = hall_view(h, MockBackend())
    assert "folded" in view and "RECENT (verbatim)" in view and "detail 49" in view


# --- the dome degrades -----------------------------------------------------
def test_dome_degrades_without_runtime(space, monkeypatch):
    monkeypatch.setattr("mor.engine.dome.probe_runtime", lambda: "")
    d = Dome(space)
    assert d.up(["wizard", "general", "warrior"]) is False
    assert d.embodied is False
    assert d.exec("warrior", "echo hi")[0] == 127


def test_blocked_ip_helper_passes_public(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    assert _blocked_ip("example.com") == ""


# --- gpu launch: stale-server cleanup and port-conflict guard ---------------
def test_clear_stale_reports_when_port_still_held(monkeypatch):
    """After killing orphan llama-servers, if something still holds the port we
    surface it (so launch can fail clearly instead of binding forever)."""
    from mor import gpu
    calls = []

    def fake_run(cargs, command, timeout=120):
        calls.append(command)
        if "ss -tln" in command:
            return 0, "LISTEN 0 128 127.0.0.1:8080 0.0.0.0:*", ""
        return 0, "", ""

    monkeypatch.setattr(gpu, "run", fake_run)
    held = gpu._clear_stale_and_check_port(["host"], 8080)
    assert "8080" in held
    assert any("pkill" in c for c in calls)  # orphans were cleared first


def test_clear_stale_returns_empty_when_port_free(monkeypatch):
    from mor import gpu
    monkeypatch.setattr(gpu, "run", lambda *a, **k: (0, "", ""))
    assert gpu._clear_stale_and_check_port(["host"], 8080) == ""
