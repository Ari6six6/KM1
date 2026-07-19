"""R4 — the Yard: forged tools return, jailed. The escape suite (S4's grave)."""

from __future__ import annotations

import os

from mor.yard import run_forged, write_forged, list_forged, run_named


def test_a_forged_tool_runs_out_of_the_host_process():
    r = run_forged("def run(args):\n import os\n return os.getpid()", {})
    assert r["ok"] and r["result"] != os.getpid()      # a different process — never in-host


def test_a_forged_tool_gets_only_its_args_not_the_harness():
    # the harness's egress rail is not in the forged namespace — it can't call web_fetch
    r = run_forged("def run(args): return 'web_fetch' in globals() or 'web_fetch' in dir(__builtins__)", {})
    assert r["ok"] and r["result"] is False
    r2 = run_forged("def run(args): return args['x'] + 1", {"x": 41})
    assert r2["result"] == 42


def test_a_crashing_tool_does_not_kill_the_realm():
    r = run_forged("def run(args): raise RuntimeError('boom')", {})
    assert r["ok"] is False and "RuntimeError" in r["error"]
    # the realm is fine: the very next call still works
    assert run_forged("def run(args): return 'alive'", {})["result"] == "alive"


def test_an_infinite_loop_is_killed_by_the_yard():
    r = run_forged("def run(args):\n while True:\n  pass", {}, cpu_s=1, timeout_s=5)
    assert r["ok"] is False and "stopped" in r["error"].lower()


def test_a_memory_bomb_is_bounded():
    r = run_forged("def run(args): return len(bytearray(3 * 1024 * 1024 * 1024))",
                   {}, mem_mb=400)
    assert r["ok"] is False                            # MemoryError under the AS limit


def test_a_tool_that_defines_no_run_is_rejected():
    r = run_forged("x = 1", {})
    assert r["ok"] is False and "run(args)" in r["error"]


def test_the_registry_persists_and_runs_a_named_tool(project):
    write_forged(project, "adder", "def run(args): return args['a'] + args['b']")
    assert list_forged(project) == ["adder"]
    assert run_named(project, "adder", {"a": 2, "b": 3})["result"] == 5
    assert run_named(project, "nope", {})["ok"] is False


def test_the_in_process_exec_path_is_absent_from_the_harness():
    # S4 is dead: no module execs forged/model source in the host process. The only
    # exec lives in the Yard's subprocess bootstrap string, which runs out-of-host.
    import mor.yard
    import mor.tools
    import mor.loop
    src = open(mor.tools.__file__).read() + open(mor.loop.__file__).read()
    assert "exec(" not in src and "eval(" not in src
