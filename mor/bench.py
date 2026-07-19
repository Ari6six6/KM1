"""The Benchmarks — the judge the Forge must satisfy.

R3's first law is *benchmarks before mutants*: an external, hash-pinned, task-level
suite that publishes one number, and exists and scores green **before** any
self-modification is proposed. This is the fitness function the Forge cannot reach.

A task is a directory ``bench/tasks/<id>/`` with ``task.json`` — {id, kind, brief,
check, script}. Kinds mirror the order kinds so the suite measures the realm's real
work, not a parallel universe:

  research — a scripted crew delivers a report; the check is programmatic (required
             facts present, sources cited, forbidden facts absent). No model-graded
             judging — string/rule checks only.
  build    — the crew writes code + a test; the check runs the test (executable
             truth) and confirms the files exist.
  recall   — the runner seeds an isolated realm's memory; the order asks a question
             answerable only from it; the check confirms the fact was recalled into
             context.

Every run uses a throwaway ``MOR_HOME`` (temp dir): benchmark work never touches the
realm's real memory, and the realm's memory never leaks into a benchmark — which
also makes runs reproducible. Determinism comes from a scripted mind + fixed
fixtures; a served mind brings honest variance, handled by the ε gate in the Forge.

Pinning: ``MANIFEST.sha256`` over ``bench/**`` and ``tests/**``; ``mor bench run``
verifies it before scoring and records it in the score event, so a mutant that
edits a test or a task is judged by the original — and the manifest is regenerated
only by an explicit ``mor bench pin`` (a human act).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def bench_dir() -> Path:
    return repo_root() / "bench"


def tasks_dir() -> Path:
    return bench_dir() / "tasks"


def manifest_path() -> Path:
    return bench_dir() / "MANIFEST.sha256"


# -- the manifest (pinning) -------------------------------------------------
def _pinned_files() -> list:
    root = repo_root()
    out = []
    for base in ("bench", "tests"):
        d = root / base
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file() and p.name != "MANIFEST.sha256" and "__pycache__" not in p.parts:
                out.append(p)
    return out


def compute_manifest() -> str:
    h = hashlib.sha256()
    for p in _pinned_files():
        rel = p.relative_to(repo_root()).as_posix()
        h.update(rel.encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def verify_manifest() -> bool:
    mp = manifest_path()
    if not mp.exists():
        return False
    return mp.read_text().strip() == compute_manifest()


def pin() -> str:
    digest = compute_manifest()
    manifest_path().write_text(digest + "\n")
    return digest


# -- tasks ------------------------------------------------------------------
def load_tasks() -> list:
    td = tasks_dir()
    tasks = []
    if not td.exists():
        return tasks
    for tj in sorted(td.glob("*/task.json")):
        try:
            task = json.loads(tj.read_text())
            task["_dir"] = tj.parent
            tasks.append(task)
        except (ValueError, OSError):
            continue
    return tasks


def _score_research(task: dict, order, project, contexts) -> float:
    report = ""
    for p in order.artifacts():
        if p.name == "report.md":
            report = p.read_text().lower()
    check = task.get("check", {})
    facts = [f.lower() for f in check.get("required_facts", [])]
    sources = [s.lower() for s in check.get("cite_sources", [])]
    forbidden = [f.lower() for f in check.get("forbidden_facts", [])]
    if any(f in report for f in forbidden):
        return 0.0
    wanted = facts + sources
    if not wanted:
        return 1.0 if report else 0.0
    hit = sum(1 for w in wanted if w in report)
    return hit / len(wanted)


def _score_build(task: dict, order, project, contexts) -> float:
    ws = project.workspace
    check = task.get("check", {})
    files = check.get("files", [])
    present = sum(1 for f in files if (ws / f).exists())
    file_score = present / len(files) if files else 1.0
    test_file = check.get("test_file")
    test_ok = 1.0
    if test_file:
        if not (ws / test_file).exists():
            test_ok = 0.0
        else:
            try:
                r = subprocess.run([sys.executable, test_file], cwd=str(ws),
                                   capture_output=True, timeout=30)
                test_ok = 1.0 if r.returncode == 0 else 0.0
            except (OSError, subprocess.TimeoutExpired):
                test_ok = 0.0
    # executable truth dominates; file presence is the tie-breaker
    return round(0.3 * file_score + 0.7 * test_ok, 4) if test_file else file_score


def _score_recall(task: dict, order, project, contexts) -> float:
    check = task.get("check", {})
    wanted = [f.lower() for f in check.get("answer_contains", [])]
    blob = " ".join(c.get("user", "") + " " + c.get("system", "") for c in contexts).lower()
    report = ""
    for p in order.artifacts():
        if p.name == "report.md":
            report = p.read_text().lower()
    # the fact must have been recalled into context AND made it into the answer
    hit = 0
    for w in wanted:
        if w in blob and w in report:
            hit += 1
    return hit / len(wanted) if wanted else 0.0


_SCORERS = {"research": _score_research, "build": _score_build, "recall": _score_recall}


def run_one(task: dict) -> float:
    """Run one task in a throwaway realm and score it 0..1. Leaves no trace in the
    caller's MOR_HOME."""
    from mor.config import Project, use_project, load_project
    from mor.llm import ScriptClient
    from mor.order import run_order

    saved_home = os.environ.get("MOR_HOME")
    saved_base = os.environ.get("MOR_BASE_URL")
    tmp = tempfile.mkdtemp(prefix="morbench-")
    try:
        os.environ["MOR_HOME"] = tmp
        os.environ.pop("MOR_BASE_URL", None)          # benchmarks run scripted/offline
        Project("bench").ensure()
        use_project("bench")
        project = load_project()
        seed = task.get("seed", {})
        if seed.get("notes"):
            project.notes_path.write_text(seed["notes"])
        contexts = []
        client = ScriptClient(task["script"]) if task.get("script") else None
        order = run_order(project, task["kind"], task["brief"], client=client,
                          echo=False, on_turn=contexts.append)
        scorer = _SCORERS.get(task["kind"], _score_research)
        return max(0.0, min(1.0, scorer(task, order, project, contexts)))
    finally:
        if saved_home is not None:
            os.environ["MOR_HOME"] = saved_home
        else:
            os.environ.pop("MOR_HOME", None)
        if saved_base is not None:
            os.environ["MOR_BASE_URL"] = saved_base
        shutil.rmtree(tmp, ignore_errors=True)


def run_suite(verify: bool = True) -> dict:
    """Run every task; return {score, breakdown, manifest, tasks}. The suite score
    is the weighted mean × 100. ``verify`` gates on the manifest (the Forge and the
    CLI always verify; a bare programmatic score can opt out)."""
    if verify and not verify_manifest():
        raise RuntimeError("bench manifest mismatch — bench/ or tests/ was modified; "
                           "run `mor bench pin` if the change is intended.")
    tasks = load_tasks()
    breakdown, total_w, total = [], 0.0, 0.0
    for task in tasks:
        w = float(task.get("weight", 1.0))
        s = run_one(task)
        breakdown.append({"id": task["id"], "kind": task["kind"], "score": round(s, 4),
                          "weight": w})
        total_w += w
        total += w * s
    score = round((total / total_w) * 100, 2) if total_w else 0.0
    return {"score": score, "breakdown": breakdown, "manifest": compute_manifest(),
            "tasks": len(tasks)}
