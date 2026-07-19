"""The Forge — the realm strengthens itself, under quarantine, judged from outside.

This is the chapter the old branch died trying to write. It survives here because
three laws are enforced by construction, not by prompt:

  LAW OF QUARANTINE — the improver works in a **git worktree**, never the live
    tree. A kept improvement is a merge; a rejected one is a discarded worktree.
    The running realm is never mutated in place; a kept change takes effect at the
    next restart, never mid-flight.
  LAW OF THE UNTOUCHABLE JUDGE — before judging, ``bench/`` and ``tests/`` are
    **restored** from the pristine tree into the worktree (overwriting whatever the
    mutant did there). A mutant that weakens a test is therefore judged by the
    original test. Construction-true, not policy-true.
  LAW OF EXTERNAL FITNESS — the only fitness term is the **benchmark delta**,
    measured by the restored judge. Forged-tool count, kept-count, graph mass:
    telemetry, never terms. JUICE = Δbenchmark, and nothing else.

The cycle: preflight (clean tree) → aim (the weakest task, or a given/dreamt brief)
→ quarantine (worktree) → propose (the crew edits inside the worktree only) → judge
(restore bench/tests, run rails, run the benchmark) → keep (merge) or reject
(discard) → record the verdict as a ledger event → clean up.

Everything runs DEMO/offline until a served mind is attached; the score comes from
the real suite either way.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from mor.bench import compute_manifest, repo_root

RAILS_DEFAULT = ["tests/test_tools.py", "tests/test_stream.py"]


def _git(repo, *args, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:200]}")
    return r.stdout


def _bench_score(tree) -> dict:
    """Run the benchmark against a tree's own code, in a subprocess rooted there —
    so a mutated ``mor/`` is what gets measured, not the live one."""
    code = ("import json; from mor.bench import run_suite; "
            "print('BENCHRESULT:' + json.dumps(run_suite(verify=False)))")
    env = {**os.environ, "PYTHONPATH": str(tree)}
    r = subprocess.run([sys.executable, "-c", code], cwd=str(tree), env=env,
                       capture_output=True, text=True, timeout=180)
    for line in r.stdout.splitlines():
        if line.startswith("BENCHRESULT:"):
            return json.loads(line[len("BENCHRESULT:"):])
    raise RuntimeError("benchmark did not report a score: "
                       + (r.stderr.strip()[-300:] or r.stdout.strip()[-300:]))


def _rails_pass(tree, rails=None) -> bool:
    """Run the rails suite against a tree — the hardening/escape tests that a
    mutation may never weaken (they are restored to pristine before this runs)."""
    paths = rails or RAILS_DEFAULT
    env = {**os.environ, "PYTHONPATH": str(tree)}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", *paths],
                       cwd=str(tree), env=env, capture_output=True, text=True, timeout=300)
    return r.returncode == 0


def weakest_brief(breakdown: list) -> str | None:
    """Aim the mutation: the lowest-scoring task is where there is something to
    win. None if everything is already perfect (nothing to improve)."""
    below = [row for row in breakdown if row["score"] < 0.999]
    if not below:
        return None
    worst = min(below, key=lambda r: r["score"])
    return (f"improve the realm so the '{worst['id']}' benchmark task ({worst['kind']}) "
            f"scores higher; it is at {worst['score']:.2f}. Edit the source in this "
            "worktree only.")


def decide(rails_ok: bool, baseline: float, new: float, epsilon: float) -> tuple:
    """The verdict, from external fitness alone. Keep only on a measured gain with
    rails intact; otherwise reject (a regression is flagged for telemetry)."""
    if not rails_ok:
        return "reject", "rails red"
    if new > baseline:
        return "keep", "measured gain"
    if new < baseline - epsilon:
        return "reject", "regression"
    return "reject", "no gain"


def _propose(worktree, brief: str, client=None) -> None:
    """The crew edits the worktree — its file tools are rooted there, so writes
    outside are impossible, not impolite (the sandbox already guarantees it)."""
    from mor.session import Session
    from mor.config import load_project
    saved_ws = os.environ.get("MOR_WORKSPACE")
    os.environ["MOR_WORKSPACE"] = str(worktree)
    try:
        Session(load_project(), echo=False, client=client).run_task(
            "You are the Smith in the Forge. " + brief + " Make one focused change.")
    finally:
        if saved_ws is not None:
            os.environ["MOR_WORKSPACE"] = saved_ws
        else:
            os.environ.pop("MOR_WORKSPACE", None)


def forge_once(repo=None, *, client=None, brief=None, epsilon: float = 1.0, tag=None,
               project=None, score_fn=None, rails_fn=None, rails=None) -> dict:
    """Run one Forge cycle and return the verdict dict. ``score_fn(tree)->dict`` and
    ``rails_fn(tree)->bool`` default to the real benchmark and rails; tests inject
    them. Never mutates the live tree except by an explicit merge on a kept gain."""
    repo = Path(repo or repo_root())
    score_fn = score_fn or _bench_score
    rails_fn = rails_fn or (lambda t: _rails_pass(t, rails))

    if _git(repo, "status", "--porcelain").strip():
        return {"verdict": "aborted", "reason": "live tree not clean"}

    baseline_result = score_fn(repo)
    baseline = float(baseline_result["score"])
    if not brief:
        brief = weakest_brief(baseline_result.get("breakdown", []))
        if not brief:
            return {"verdict": "nothing", "reason": "every task already perfect",
                    "baseline": baseline}

    tag = tag or time.strftime("%Y%m%d-%H%M%S")
    branch = f"forge/{tag}"
    wt = repo / ".forge" / tag
    _git(repo, "worktree", "add", "-b", branch, str(wt), "HEAD")
    verdict_event = None
    try:
        _propose(wt, brief, client)
        patch_summary = _git(wt, "diff", "--stat").strip().splitlines()[-1:] or ["(no change)"]

        # LAW OF THE UNTOUCHABLE JUDGE — restore the judge before it judges.
        _git(wt, "checkout", "HEAD", "--", "bench", "tests")
        manifest_hash = compute_manifest()

        rails_ok = rails_fn(wt)
        new = float(score_fn(wt)["score"])
        delta = round(new - baseline, 4)
        verdict, reason = decide(rails_ok, baseline, new, epsilon)

        if verdict == "keep":
            _git(wt, "add", "-A")
            _git(wt, "commit", "-m", f"forge: {brief[:60]}")
            _git(repo, "merge", branch, "-m", f"forge: keep — {reason} (+{delta})")

        verdict_event = {"kind": "forge.verdict", "brief": brief, "verdict": verdict,
                         "reason": reason, "baseline": baseline, "new": new,
                         "delta": delta, "juice": new, "manifest_hash": manifest_hash,
                         "patch_summary": patch_summary[0].strip()}
    finally:
        _git(repo, "worktree", "remove", "--force", str(wt), check=False)
        if verdict_event is None or verdict_event["verdict"] != "keep":
            _git(repo, "branch", "-D", branch, check=False)

    if project is not None and verdict_event is not None:
        from mor.ledger import record
        record(project, "forge.verdict", **{k: v for k, v in verdict_event.items()
                                            if k != "kind"})
    return verdict_event
