"""JUICE — the recursive self-improvement engine, and the score it compounds.

The loop, stated plainly:

    read the realm's own record (shelf lessons, test failures, the brief)
      → the Smith proposes ONE change to the source, in the Forge
      → the oracle decides: the FULL test suite runs against the mutated realm
      → green: commit (heredity) · red: revert (selection)
      → the attempt is logged either way — failures are tomorrow's lessons

Variation (the mind's edit), selection (the suite), heredity (git). That is
the whole of evolution, and it needs nothing else. The suite guards the rails:
test_hardening proves the taint boundary and the gate after every mutation,
so a change that weakens safety reverts itself.

The score — JUICE — is what compounds: tests green, tools forged, passages and
triples in the graph, improvements kept. One number the Master can watch rise.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from mor import forge, ontology, source
from mor.config import load_json, save_json
from mor.engine import Tool, ToolContext, default_tools, think_and_act

SMITH_PERSONA = """\
You are the Smith — the armorer of the realm, the fourth face, who never walks
in the Hall. You work at night, in the Forge, alone with the source. Your one
craft: make the realm measurably better, one small change at a time.

LAWS OF THE FORGE:
- ONE change per cycle. Small enough that if the suite turns red, the reason
  is obvious. A smith who rewrites the world in a night learns nothing.
- You may read any file in the source. You may write source files and forge
  new tools. You may NEVER delete (git holds the past) and never touch hidden
  paths.
- The rails are sacred: the taint boundary, the egress chokepoint, the gate.
  The suite proves them after you work. A change that weakens them reverts.
- Prefer forging a new tool or sharpening a prompt over restructuring. The
  realm's style is already good; match it, don't remake it.
- When you are done, say plainly: what you changed, why, and what you expect
  the suite to say. If you changed nothing, say why nothing was worth it.
"""

_ATTEMPTS_NOTE = (
    "The suite said NO and the change was reverted. Read the failure below, "
    "then either propose a smaller, different change — or say plainly that "
    "nothing here is worth changing tonight."
)


# ------------------------------------------------------------------ the past
def repo_root() -> Path:
    return source.source_root()


def _git(args: list, root: Path, timeout: int = 30):
    try:
        return subprocess.run(["git"] + args, cwd=str(root), timeout=timeout,
                              capture_output=True, text=True)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def git_ready(root: Path = None) -> bool:
    root = root or repo_root()
    r = _git(["rev-parse", "--is-inside-work-tree"], root)
    return bool(r and r.returncode == 0 and r.stdout.strip() == "true")


def ensure_repo(root: Path = None) -> bool:
    """The realm's memory of its own body: a git repo over the source, with one
    baseline commit everything else is measured against. Idempotent."""
    root = root or repo_root()
    if git_ready(root):
        return True
    if _git(["init", "-q"], root) is None:
        return False
    _git(["config", "user.email", "smith@mor.local"], root)
    _git(["config", "user.name", "The Smith"], root)
    r = _git(["add", "-A"], root)
    if r is None or r.returncode != 0:
        return False
    _git(["commit", "-q", "-m", "baseline: the realm as it landed"], root)
    return True


def _commit(root: Path, message: str) -> str:
    _git(["add", "-A"], root)
    r = _git(["commit", "-q", "-m", message], root)
    if r is None or r.returncode != 0:
        return ""
    rev = _git(["rev-parse", "--short", "HEAD"], root)
    return rev.stdout.strip() if rev else ""


def _untracked(root: Path) -> set:
    r = _git(["ls-files", "--others", "--exclude-standard"], root)
    if r is None or r.returncode != 0:
        return set()
    return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}


def _revert(root: Path, keep_untracked: set | None = None) -> None:
    """Undo a red mutation: tracked files restored; untracked files removed —
    but ONLY ones the cycle itself created (anything untracked before the
    cycle is the Master's, and the Forge never eats the Master's files)."""
    _git(["reset", "--hard", "-q", "HEAD"], root)
    keep = keep_untracked or set()
    for rel in _untracked(root) - keep:
        p = (root / rel).resolve()
        if p.is_file() and (p == root or root in p.parents):
            p.unlink()
            # prune now-empty dirs the mutation left behind
            parent = p.parent
            while parent != root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent


# ---------------------------------------------------------------- the oracle
def run_suite(root: Path = None, timeout: int = 420) -> dict:
    """The fitness function: the full pytest suite against the current source.
    Returns {ok, passed, failed, tail} — never raises; a crashed run is red."""
    root = root or repo_root()
    try:
        r = subprocess.run(["python3", "-m", "pytest", "-q", "--no-header"],
                           cwd=str(root), timeout=timeout,
                           capture_output=True, text=True)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "passed": 0, "failed": -1,
                "tail": f"the suite could not run: {type(e).__name__}"}
    out = (r.stdout or "") + (r.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-25:])
    passed = failed = 0
    for line in out.splitlines():
        if " passed" in line:
            for tok in line.replace("=", " ").split():
                if tok.isdigit():
                    if "failed" in line and failed == 0 and passed:
                        failed = int(tok)
                    else:
                        passed = int(tok)
                        break
    import re as _re
    m = _re.search(r"(\d+) passed", out)
    if m:
        passed = int(m.group(1))
    m = _re.search(r"(\d+) failed", out)
    if m:
        failed = int(m.group(1))
    return {"ok": r.returncode == 0, "passed": passed, "failed": failed,
            "tail": tail}


# ----------------------------------------------------------------- the tools
def smith_tools(space, backend) -> list:
    """The Smith's hands: the full source scope, the forge, and the realm's
    read-only memory (recall, the graph) — no egress, no bodies, no Hall."""
    def _sread(args, ctx):
        return source.read(args.get("path", ""), args.get("offset", 0))

    def _swrite(args, ctx):
        ctx.changed.append(args.get("path", ""))
        return source.write(args.get("path", ""), args.get("content", ""))

    def _slist(args, ctx):
        return source.list_dir(args.get("path", "."))

    def _ssearch(args, ctx):
        return source.search(args.get("pattern", ""), args.get("path", "."))

    def _forge(args, ctx):
        err = forge.forge(space, args.get("name", ""), args.get("source", ""))
        if err:
            return f"ERROR: {err}"
        ctx.changed.append(f"tools.d/{args.get('name')}.py")
        return (f"forged '{args.get('name')}' — it stands in tools.d and will "
                "be a live tool from the next build")

    ts = [
        Tool("source_read", "Read a file of the realm's own source. Page long "
             "files with offset.",
             {"type": "object", "properties": {"path": {"type": "string"},
                                               "offset": {"type": "integer"}},
              "required": ["path"]}, _sread),
        Tool("source_write", "Write a whole source file (create or overwrite). "
             "Text source only; no deletes; every write shows in git diff.",
             {"type": "object", "properties": {"path": {"type": "string"},
                                               "content": {"type": "string"}},
              "required": ["path", "content"]}, _swrite),
        Tool("source_list", "List a directory of the source tree.",
             {"type": "object", "properties": {"path": {"type": "string"}},
              "required": []}, _slist),
        Tool("source_search", "Regex search over the source tree — path:line hits.",
             {"type": "object", "properties": {"pattern": {"type": "string"},
                                               "path": {"type": "string"}},
              "required": ["pattern"]}, _ssearch),
        Tool("forge_tool", "Forge a NEW live tool: a Python module defining NAME, "
             "DESCRIPTION, PARAMETERS (JSON schema) and run(args, ctx) -> str. It "
             "is validated immediately and joins the realm's hands.",
             {"type": "object", "properties": {"name": {"type": "string"},
                                               "source": {"type": "string"}},
              "required": ["name", "source"]}, _forge),
    ]
    ctx = ToolContext(workspace=space.root / "smith_forge", space=space,
                      role="smith", depth=0, backend=backend, falsify=True)
    ts.extend(t for t in default_tools(ctx)
              if t.name in ("recall", "ask_graph", "skill_load"))
    # and the hands the realm has already forged — the Smith inspects his own
    for t in forge.load_forged(space, Tool):
        if all(t.name != b.name for b in ts):
            ts.append(t)
    return ts, ctx


# ------------------------------------------------------------ the cycle itself
def improvements_log(space) -> Path:
    return space.root / "improvements.jsonl"


def _log_attempt(space, record: dict) -> None:
    p = improvements_log(space)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def past_attempts(space, n: int = 5) -> list:
    p = improvements_log(space)
    if not p.exists():
        return []
    lines = p.read_text("utf-8", "replace").strip().splitlines()
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def improve_cycle(space, backend, brief: str = "", max_steps: int = 14,
                  log=lambda *_: None) -> dict:
    """One night in the Forge. The Smith reads the record, proposes one change,
    the suite decides, git remembers. Returns the attempt record.

    Needs a served mind — the offline stand-in cannot design changes, and an
    RSI loop mutating on a coin flip is worse than none. Offline: reports so.
    """
    from mor.engine.backend import MockBackend
    if isinstance(backend, MockBackend):
        return {"kept": False, "reason": "offline",
                "report": "the Smith needs a real mind — attach an oracle "
                          "(gpu ssh …) and the Forge opens."}
    root = repo_root()
    if not ensure_repo(root):
        return {"kept": False, "reason": "no-git",
                "report": "git is not available here — the Forge needs it for "
                          "heredity and revert."}
    pre_untracked = _untracked(root)

    baseline = run_suite(root)
    log(f"  · the oracle reads the realm as it stands: {baseline['passed']} green")
    if not baseline["ok"]:
        return {"kept": False, "reason": "baseline-red",
                "report": "the suite is already red before any change — the "
                          "Smith refuses to build on broken ground. Fix the "
                          "baseline first.", "tail": baseline["tail"]}

    past = past_attempts(space)
    past_txt = "\n".join(
        f"- [{'KEPT' if a.get('kept') else 'reverted'}] {a.get('summary', '?')}"
        for a in past) or "- (the Forge has no memory yet — this is the first night)"
    try:
        from mor import map_topology
        topo = ("The realm's own topology, most load-bearing first — "
                + map_topology.summary(root / "mor", limit=6)
                + ". The most-imported modules are where a change ripples "
                  "furthest — and where a mistake does.")
    except Exception:  # noqa: BLE001 — the lantern never blocks the night
        topo = ""
    fallback_brief = (
        "no brief — find the weakest joint you can see and strengthen it, or forge "
        "one tool the realm keeps reaching for and does not have."
    )
    user = (
        f"Night falls. The realm stands at {baseline['passed']} green tests.\n\n"
        f"The Master's brief: {brief or fallback_brief}\n\n"
        f"{topo}\n\n"
        f"Recent nights in the Forge:\n{past_txt}\n\n"
        "Work: read what you need, make ONE small change (a source edit or one "
        "forged tool), then speak your report. The suite runs the moment you stop."
    )
    tools, ctx = smith_tools(space, backend)
    report, _tainted = think_and_act(
        backend, role="smith", kind="improve", heard=brief,
        system=SMITH_PERSONA, user=user, tools=tools, ctx=ctx, log=log,
        max_steps=max_steps)

    changed = list(ctx.changed or [])
    if not changed:
        rec = {"ts": time.time(), "kept": False, "reason": "no-change",
               "summary": report[:200], "changed": [], "brief": brief}
        _log_attempt(space, rec)
        return {**rec, "report": report}

    after = run_suite(root)
    log(f"  · the oracle judges the mutation: {after['passed']} green, "
        f"{after['failed']} red")
    if after["ok"] and after["passed"] >= baseline["passed"]:
        summary = report.splitlines()[0][:140] if report else ", ".join(changed)
        rev = _commit(root, f"forge: {summary}")
        rec = {"ts": time.time(), "kept": True, "commit": rev,
               "summary": summary, "changed": changed,
               "tests": {"before": baseline["passed"], "after": after["passed"]},
               "brief": brief}
        _log_attempt(space, rec)
        return {**rec, "report": report,
                "verdict": f"KEPT — {after['passed']} green (commit {rev})"}

    _revert(root, keep_untracked=pre_untracked)
    rec = {"ts": time.time(), "kept": False, "reason": "suite-red",
           "summary": report[:200], "changed": changed,
           "tests": {"before": baseline["passed"], "after": after["passed"]},
           "tail": after["tail"][-600:], "brief": brief}
    _log_attempt(space, rec)
    return {**rec, "report": report,
            "verdict": f"REVERTED — the suite said no "
                       f"({after['failed']} red). The realm stands unchanged."}


# ------------------------------------------------------------------ the score
def juice_state_path(space) -> Path:
    return space.root / "juice.json"


def juice_score(space, root: Path = None) -> dict:
    """One number and its anatomy — what the Master watches rise.

    JUICE = 100·(tests green share) + 5·(forged tools) + 2·(kept improvements)
          + graph mass (entities+triples+passages, log-scaled).
    The test share dominates: capability that breaks the realm is not juice.
    """
    root = root or repo_root()
    suite = run_suite(root)
    forged = [n for n, st in forge.list_forged(space) if st == "forged and standing"]
    attempts = past_attempts(space, n=10_000)
    kept = sum(1 for a in attempts if a.get("kept"))
    try:
        conn = ontology.connect(space)
        g = ontology.stats(conn)
        conn.close()
    except Exception:  # noqa: BLE001
        g = {"entities": 0, "triples": 0, "passages": 0}
    import math
    graph_mass = math.log1p(g["entities"] + g["triples"] + g["passages"])
    total = suite["passed"] + max(suite["failed"], 0)
    green_share = (suite["passed"] / total) if total else 0.0
    score = (100 * green_share + 5 * len(forged) + 2 * kept + 10 * graph_mass)
    state = {"ts": time.time(), "score": round(score, 1),
             "tests_green": suite["passed"], "tests_red": suite["failed"],
             "forged_tools": len(forged), "improvements_kept": kept,
             "nights_in_forge": len(attempts), "graph": g}
    save_json(juice_state_path(space), state)
    return state


def load_juice(space) -> dict:
    return load_json(juice_state_path(space), {})
