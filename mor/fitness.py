"""The Gate — the scalar that closes the loop.

The realm's `verifying` state used to check one thing: that a report file existed
and had bytes in it. A confidently wrong answer verified green. This module is the
missing muscle — a real fitness read on the artifact against a rubric frozen
*before* the work, so an order can catch itself being wrong and try again.

The shape, argued out over four letters with the swarm and settled:

  * **f is a vector, not a number.** Named sub-scores (facts, citations, files,
    tests) aggregate to one scalar the gate reads; the *retry* consumes the failing
    components, not the scalar — a bare number is one bit per attempt.
  * **The gate is sound, terminating, keep-best.** It never delivers below θ; it
    always halts (a hard attempt budget); and it ships ``argmax`` over the attempts,
    so the trajectory may thrash but the deliverable can't regress.
  * **Two walls make the exam untouchable.** The rubric is recorded as an event at
    ``planned`` (temporal wall — it provably predates the work, ``cat`` proves it)
    and is *never spoken into the Hall* (contextual wall — the crew shares one
    transcript, so a rubric read aloud is a rubric taught-to). It rides
    ``order.record``; only ``Transcript`` feeds model context. Two channels, one
    object.
  * **No poison, no license.** With no calibration behind it (offline, or a kind
    whose fixtures nobody wrote yet) the gate runs *advisory*: it scores, records,
    flags — and delivers, exactly as the realm did before. It blocks only where a
    calibration event says the numbers hold. The DEMO-delivers promise is kept.

θ, D, and the armed/advisory verdict are not set here — they are read from the
calibration event (``calibrate.py``), which measures them against a poisoned
fixture corpus. This file grades; that one earns the right to block.
"""

from __future__ import annotations

import re

from mor import bench
from mor.config import load_json

# A sub-score below the floor is "failing" — it names itself in the critique the
# next attempt is coached with.
_FLOOR = 0.999

_STOP = frozenset(
    "the a an and or of to in on at for with by from as is are was were be to and "
    "which who how why what when this that these those it its into over about your "
    "our their a an cite source sources please give list top best".split())


# -- the rubric: frozen at planned, kept off the Hall ------------------------
def _salient(brief: str, limit: int = 6) -> list:
    """The load-bearing terms of a brief — a deterministic scaffold for the
    offline rubric. Honest and labelled ``template``; a served planner writes a
    real one. The mechanism (a frozen, hidden rubric) is what matters here, not
    the cleverness of the offline extraction."""
    seen, out = set(), []
    for t in re.findall(r"[a-z][a-z0-9_+.-]{2,}", brief.lower()):
        if t in _STOP or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:limit]


def make_rubric(kind: str, brief: str, client=None) -> dict:
    """The acceptance rubric for an order — a closed list of typed checks. Offline
    it is a deterministic ``template``; the ``client`` seam is where a served
    planner authors a real one (same schema), still emitted as an event, never a
    spoken line. Returns ``{"authored_by", "checks"}``."""
    checks: list = []
    if kind == "research":
        for term in _salient(brief):
            checks.append({"type": "required_fact", "value": term})
        if re.search(r"\b(cite|source|sources|reference)\b", brief.lower()):
            checks.append({"type": "citation_substring", "value": "http"})
    elif kind == "fetch":
        checks.append({"type": "nonempty_report", "value": ""})
    # build's real rubric (which files, which behaviours) needs a planner or a
    # human; the offline template stays minimal rather than guess and grade on a
    # lie. Absent checks → an advisory, non-blocking read.
    return {"authored_by": "template", "checks": checks}


# -- scoring: the vector, then the scalar ------------------------------------
_DETERMINISTIC = {
    "required_fact": "required_facts",
    "forbidden_claim": "forbidden_absent",
    "citation_substring": "citations",
    "files_present": "files_present",
    "test_passes": "tests_pass",
    "nonempty_report": "nonempty",
}


def score(kind: str, brief: str, report: str, workspace, rubric: dict,
          client=None) -> dict:
    """Grade one artifact against its frozen rubric. Returns a FitnessVector:
    ``{vector, weights, scalar, failing, critique}``. Deterministic legs need no
    model; the critic leg (a served judge) enters weighted by its measured
    discrimination D and is absent — weight 0 — until a calibration earns it."""
    checks = (rubric or {}).get("checks", [])
    buckets: dict = {}
    for c in checks:
        buckets.setdefault(c.get("type"), []).append(c.get("value", ""))

    vector: dict = {}
    for ctype, values in buckets.items():
        name = _DETERMINISTIC.get(ctype)
        if name == "required_facts":
            vector[name] = bench.check_required(report, values)
        elif name == "forbidden_absent":
            vector[name] = bench.check_forbidden_absent(report, values)
        elif name == "citations":
            vector[name] = bench.check_required(report, values)
        elif name == "files_present":
            paths = [p for v in values for p in (v if isinstance(v, list) else [v]) if p]
            vector[name] = bench.check_files_present(workspace, paths)
        elif name == "tests_pass":
            vector[name] = min(bench.check_test_passes(workspace, v) for v in values)
        elif name == "nonempty":
            vector[name] = 1.0 if (report or "").strip() else 0.0

    # The critic leg — a served judge, weighted by D (from calibration). Off until
    # earned: absent here means weight 0, which is the swarm's law made structural.
    weights = {name: 1.0 for name in vector}
    weights["critic"] = 0.0

    if not vector:
        # nothing to check (e.g. a build with a template rubric) — an honest,
        # content-only floor so the read is defined but never blocks on its own.
        vector = {"nonempty": 1.0 if (report or "").strip() else 0.0}
        weights = {"nonempty": 1.0, "critic": 0.0}

    total_w = sum(weights[n] for n in vector) or 1.0
    scalar = round(sum(vector[n] * weights[n] for n in vector) / total_w, 4)
    failing = sorted(n for n, v in vector.items() if v < _FLOOR)
    critique = _critique(kind, failing, vector) if failing else ""
    return {"vector": vector, "weights": weights, "scalar": scalar,
            "failing": failing, "critique": critique}


_COMPONENT_HINT = {
    "required_facts": "the brief's key points aren't all addressed",
    "citations": "claims are made without a cited source (include a URL)",
    "forbidden_absent": "the report contains a claim the rubric forbids",
    "files_present": "expected files were not produced in the workspace",
    "tests_pass": "the test did not pass",
    "nonempty": "the report is empty",
}


def _critique(kind: str, failing: list, vector: dict) -> str:
    bits = [f"{n} ({vector[n]:.2f}): {_COMPONENT_HINT.get(n, 'below the bar')}"
            for n in failing]
    return "fell short on — " + "; ".join(bits)


# -- the verdict: advisory until a calibration arms it -----------------------
def _calibration_path(project):
    return project.root / "realm" / "calibration.json"


def calibration(project, kind: str) -> "dict | None":
    """The armed measuring stick for a kind, or None. Written by ``calibrate.py``;
    read here to decide whether the gate blocks or merely watches."""
    data = load_json(_calibration_path(project), {})
    return data.get(kind)


def gate(scalar: float, kind: str, project) -> tuple:
    """The verdict on one score. ``("advisory", None)`` when no armed calibration
    stands behind this kind — the gate watches but never blocks, so a fresh clone
    and an uncalibrated kind deliver exactly as before. ``("accept"|"reject", θ)``
    only when a calibration event has licensed the cut."""
    cal = calibration(project, kind)
    if not cal or cal.get("gate") != "armed":
        return "advisory", None
    theta = float(cal.get("theta", 1.0))
    return ("accept" if scalar >= theta else "reject"), theta


def coaching(carry: dict) -> str:
    """The line a retry hears — the failing components and the critique, spoken
    into the Hall as coaching *after* a scored failure. This is deliberately on
    the near side of the contextual wall: the candidate never reads the exam cold,
    but a candidate who already failed is told where. Hiding this would blind the
    hill-climb."""
    failing = ", ".join(carry.get("failing") or []) or "the brief"
    critique = carry.get("critique") or ""
    return ("A previous attempt was scored and fell short. Weakest parts: "
            f"{failing}. {critique} Fix these specifically before you finish.")
