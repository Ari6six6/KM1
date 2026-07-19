"""The Yard — where model-written code does time.

The old branch's tenth sin (S4): a forged tool ``exec``'d in the harness process
with full host privileges, guarded by a substring check. The Yard kills that by
construction. A forged tool is a small module the crew writes — ``run(args)`` — and
it **never runs in the host process**. It runs as a **subprocess**, spoken to over a
tiny JSON RPC (JSON args in, JSON result out), under resource limits (CPU, address
space, no core dump) and a wall-clock timeout. It can crash, loop, or bomb memory
and the realm does not notice: the parent reaps it and reports a structured error.

The subprocess boundary is enforced here in pure stdlib. The *network* and
*filesystem* jail — ``--cap-drop ALL --network internal`` inside a body — is the
container layer (Docker/netns), and it slots onto this same subprocess seam when a
runtime is present; without one the forged tool is out-of-process and bounded but
not network-isolated, which the Yard states plainly rather than pretends.

Deliverable proof: the escape suite (a crashing tool, an infinite loop, a memory
bomb) all fail *red inside the Yard* and green for the realm — and a forged tool's
namespace never contains the harness, its tools, or its egress.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

DEFAULT_CPU_S = 2
DEFAULT_MEM_MB = 512
DEFAULT_TIMEOUT_S = 5

# The bootstrap runs *in the subprocess*: it sets the jail's resource limits, then
# execs the forged source in a fresh namespace and calls run(args). The host process
# never execs forged code — that is the whole point.
_BOOTSTRAP = r"""
import sys, json, resource
cpu, mem_bytes, tool = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
try:
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
except (ValueError, OSError):
    pass
args = json.load(sys.stdin)
ns = {}
try:
    with open(tool) as f:
        exec(compile(f.read(), tool, "exec"), ns)   # in THIS jailed subprocess only
    if "run" not in ns or not callable(ns["run"]):
        raise ValueError("a forged tool must define run(args)")
    result = ns["run"](args)
    json.dumps(result)  # must be JSON-serializable
    sys.stdout.write("YARD:" + json.dumps({"ok": True, "result": result}))
except Exception as e:
    sys.stdout.write("YARD:" + json.dumps({"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}))
"""


def run_forged(source: str, args=None, *, cpu_s: int = DEFAULT_CPU_S,
               mem_mb: int = DEFAULT_MEM_MB, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
    """Run a forged tool's ``source`` in a jailed subprocess. Returns
    {ok, result} or {ok: False, error}. Never raises for a misbehaving tool — a
    crash, a loop, or a memory bomb becomes a structured error, not a dead realm."""
    args = args if args is not None else {}
    fd, path = tempfile.mkstemp(suffix="_forged.py", prefix="yard-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(source)
        try:
            p = subprocess.run(
                [sys.executable, "-c", _BOOTSTRAP, str(cpu_s), str(mem_mb * 1024 * 1024), path],
                input=json.dumps(args), capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout — the Yard killed a runaway tool"}
        for line in p.stdout.splitlines():
            if line.startswith("YARD:"):
                return json.loads(line[len("YARD:"):])
        # no result line: killed by a resource limit (CPU/memory) before it could report
        reason = "CPU/memory limit" if p.returncode and p.returncode < 0 else \
                 (p.stderr.strip()[-160:] or f"exit {p.returncode}")
        return {"ok": False, "error": f"the Yard stopped the tool ({reason})"}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# -- a small registry so forged tools persist between sessions --------------
def _forged_dir(project):
    return project.root / "forged"


def write_forged(project, name: str, source: str) -> None:
    d = _forged_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.py").write_text(source)


def list_forged(project) -> list:
    d = _forged_dir(project)
    return sorted(p.stem for p in d.glob("*.py")) if d.exists() else []


def run_named(project, name: str, args=None, **limits) -> dict:
    p = _forged_dir(project) / f"{name}.py"
    if not p.exists():
        return {"ok": False, "error": f"no forged tool named '{name}'"}
    return run_forged(p.read_text(), args, **limits)
