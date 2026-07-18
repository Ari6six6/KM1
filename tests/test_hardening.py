"""The hardening suite — one pin per fix from the review.

Each test names the failure it locks out: a malformed paste must never crash
the shell, a failed body must never haunt the dome, a gate entry is stored the
way the gate matches, the day is sealed however the shell ends.
"""

from __future__ import annotations

import pytest

from mor.config import Space, save_json, valid_space_name
from mor.engine import Dome, ScriptBackend, ToolContext, default_tools
from mor.engine.tools import _read_file, _search_workspace
from mor import gpu


# --- a malformed -L forward must never take the shell down ------------------
def test_parse_forward_survives_malformed_input():
    assert gpu.parse_forward(["-L", "abc:localhost:8080"]) is None  # no ValueError
    assert gpu.parse_forward(["-L", "8080:localhost:nope"]) is None
    assert gpu.parse_forward(["-L", "8080"]) is None
    assert gpu.parse_forward(["-L", "0:localhost:8080"]) is None      # port range
    assert gpu.parse_forward(["-L", "8080::8080"]) is None            # empty host
    assert gpu.parse_forward([]) is None


def test_parse_forward_valid_forms():
    assert gpu.parse_forward(["-p", "11808", "root@box",
                              "-L", "8080:localhost:8081"]) == (8080, "localhost", 8081)
    assert gpu.parse_forward(["-L8080:localhost:8081"]) == (8080, "localhost", 8081)
    assert gpu.parse_forward(["-L", "8080:8081"]) == (8080, "127.0.0.1", 8081)


# --- the magic port slide: a squatted box port never stops a serve -----------
def test_replace_forward_swaps_only_the_box_side_port():
    assert gpu.replace_forward(
        ["-p", "11808", "root@box", "-L", "8080:localhost:8080"], 18080) == \
        ["-p", "11808", "root@box", "-L", "8080:localhost:18080"]
    assert gpu.replace_forward(["-L8080:8080"], 18080) == ["-L8080:18080"]
    assert gpu.replace_forward(["-L", "8080:18080"], 18080) == ["-L", "8080:18080"]
    assert gpu.replace_forward(["root@box"], 18080) == ["root@box"]


def _fake_box(monkeypatch, held_ports):
    import mor.gpu as g
    calls = []

    def fake_run(cargs, command, timeout=120):
        calls.append(command)
        if "ss -tln" in command:
            for p in held_ports:
                if f"grep ':{p} '" in command:
                    return 0, f"LISTEN 0 128 127.0.0.1:{p} 0.0.0.0:*", ""
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr(g, "run", fake_run)
    monkeypatch.setattr(g, "server_running", lambda cargs: False)
    monkeypatch.setattr(g, "_install_llama", lambda *a, **k: None)
    monkeypatch.setattr(g, "_register_cuda_libs", lambda *a, **k: None)
    return calls


def test_launch_slides_a_held_port_on_its_own(monkeypatch):
    from mor.models import GLM
    calls = _fake_box(monkeypatch, held_ports={8080})
    port = gpu.launch(["host"], GLM, 1, 16384, 0.92, 8080, print, auto_port=True)
    assert port == 18080
    assert any("--port 18080" in c for c in calls)  # the server binds the slid port


def test_launch_without_auto_port_still_refuses(monkeypatch):
    from mor.models import GLM
    _fake_box(monkeypatch, held_ports={8080})
    with pytest.raises(gpu.ProvisionError):
        gpu.launch(["host"], GLM, 1, 16384, 0.92, 8080, print)


def test_launch_raises_when_the_slide_target_is_also_held(monkeypatch):
    from mor.models import GLM
    _fake_box(monkeypatch, held_ports={8080, 18080})
    with pytest.raises(gpu.ProvisionError):
        gpu.launch(["host"], GLM, 1, 16384, 0.92, 8080, print, auto_port=True)


# --- the gate stores what the gate matches ----------------------------------
def test_authorize_normalizes_to_a_bare_host(space):
    assert space.authorize("HTTPS://Example.com/some/path?q=1") == "example.com"
    assert space.egress_allowed("example.com")
    assert space.authorize("  MIXED-case.org  ") == "mixed-case.org"
    assert space.egress_allowed("mixed-case.org")
    assert space.authorize("*") == "*"
    assert space.egress_allowed("anything.example")


def test_authorize_refuses_names_with_no_host(space):
    assert space.authorize("") == ""
    assert space.authorize("   ") == ""
    assert space.authorize('"') == ""               # a stray quote is not a host
    assert space.authorize("http://exa mple.com") == ""  # spaces are not hosts
    assert space.authorize("-bad-.com") == ""
    assert space.allowlist() == []  # the gate stayed shut


def test_authorize_is_exact_match_not_suffix(space):
    space.authorize("example.com")
    assert not space.egress_allowed("evilexample.com")
    assert not space.egress_allowed("www.example.com")


# --- the dome records only bodies that truly rose ----------------------------
def _fake_runtime(monkeypatch, run_rc=0):
    import mor.engine.dome as dm
    calls = []

    def fake_sh(cmd, timeout=60):
        calls.append(cmd)
        if "version" in cmd:
            return 0, "Docker", ""
        if " ps " in cmd:
            return 0, "", ""          # nothing already running
        if " run -d " in cmd:
            return run_rc, "", "boom" if run_rc else ""
        return 0, "", ""

    monkeypatch.setattr(dm, "_sh", fake_sh)
    monkeypatch.setattr(dm, "probe_runtime", lambda: "docker")
    return calls


def test_a_body_that_fails_to_rise_is_not_recorded(space, monkeypatch):
    _fake_runtime(monkeypatch, run_rc=1)
    d = Dome(space)
    assert d.up(["wizard", "general", "warrior"]) is False
    assert d.embodied is False
    assert d.bodies == {}  # no phantoms — run_shell is never offered


def test_partial_rise_records_only_the_living(space, monkeypatch):
    import mor.engine.dome as dm
    risen = []

    def fake_sh(cmd, timeout=60):
        if "version" in cmd:
            return 0, "Docker", ""
        if " ps " in cmd:
            return 0, "", ""
        if " run -d " in cmd:
            if "warrior" in cmd:
                return 1, "", "boom"
            risen.append(cmd)
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr(dm, "_sh", fake_sh)
    monkeypatch.setattr(dm, "probe_runtime", lambda: "docker")
    d = Dome(space)
    assert d.up(["wizard", "general", "warrior"]) is True
    assert set(d.bodies) == {"wizard", "general"}
    assert d.exec("warrior", "echo hi")[0] == 127  # honestly bodiless


def test_a_stopped_husk_is_cleared_before_the_fresh_body_rises(space, monkeypatch):
    calls = _fake_runtime(monkeypatch, run_rc=0)
    d = Dome(space)
    assert d.up(["wizard"]) is True
    assert any("rm -f" in c and "mor-test-wizard" in c for c in calls)


# --- state writes are atomic; the record never tears -------------------------
def test_save_json_leaves_no_tmp_and_reads_back(space):
    p = space.root / "world.json"
    save_json(p, {"places": {"example.com": {"visits": 1}}})
    assert not (space.root / "world.json.tmp").exists()
    import json
    assert json.loads(p.read_text())["places"]["example.com"]["visits"] == 1


# --- space names stay inside MOR_HOME ----------------------------------------
def test_space_name_validation():
    assert valid_space_name("realm")
    assert valid_space_name("my-realm_2.0")
    for bad in ("", "..", "../etc", "a/b", "a\\b", ".hidden", "a b", "x" * 65):
        assert not valid_space_name(bad)


# --- read guards: directories and giants --------------------------------------
def _ctx(space, role="wizard"):
    ws = space.root / "population" / role / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ToolContext(workspace=ws, space=space, can_egress=False,
                       tainted=[], role=role)


def test_read_file_names_a_directory_instead_of_crashing(space):
    ctx = _ctx(space)
    out = _read_file({"path": "."}, ctx)
    assert out.startswith("ERROR") and "list_dir" in out


def test_read_file_refuses_a_giant_file(space, monkeypatch):
    import mor.engine.tools as tools
    monkeypatch.setattr(tools, "_READ_MAX_BYTES", 100)
    ctx = _ctx(space)
    (ctx.workspace / "giant.bin").write_text("x" * 1000)
    out = _read_file({"path": "giant.bin"}, ctx)
    assert out.startswith("ERROR") and "too big" in out


def test_search_scans_a_bounded_window_of_each_line(space):
    ctx = _ctx(space)
    (ctx.workspace / "long.txt").write_text("a" * 5000 + "needle")
    assert "no matches" == _search_workspace({"pattern": "needle"}, ctx)


# --- taint rides every turn, dawn included ------------------------------------
def test_a_wake_turn_that_crosses_outside_is_recorded(space, monkeypatch):
    """Before the fix, wake/wall/chant turns ran with throwaway sinks: a Warrior
    fetching at dawn tainted nothing. Now the day's lists ride every turn."""
    import socket
    from mor.realm import Realm

    monkeypatch.setattr("mor.engine.dome.probe_runtime", lambda: "")
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])

    class FakeResp:
        status = 200

        def read(self, n=None):
            return b"dawn news"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("mor.engine.tools._open_one_hop", lambda *a, **k: FakeResp())
    space.authorize("example.com")

    # wizard wake, general wake, warrior wake (fetch + line), general's greeting.
    # light() refreshes the mind from make_backend, so the script takes the
    # throne there, not on the realm directly.
    script = ScriptBackend([
        {"text": "awake"},
        {"text": "awake"},
        {"tool": "web_fetch", "args": {"url": "http://example.com/"}},
        {"text": "awake, and I looked outside"},
        {"text": "ready, Master"},
    ])
    monkeypatch.setattr("mor.realm.make_backend", lambda: (script, "script"))

    r = Realm(space, echo=False)
    r.light()
    assert r._tainted == ["example.com"]
    r.dark()
