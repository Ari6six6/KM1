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

import json
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


_ACCEPTANCE_FILE = "acceptance_test.py"


def make_rubric(kind: str, brief: str, client=None, workspace=None) -> dict:
    """The acceptance rubric for an order — a closed list of typed checks, frozen
    here at ``planned`` and never spoken into the Hall. Offline it is a
    deterministic ``template``; the ``client`` seam is where a served planner
    authors a real one (same schema). Returns ``{"authored_by", "checks"}``.

    For **build**, if the operator (or a planner) has dropped an ``acceptance_test.py``
    in the workspace, its *content* is frozen into the rubric now, before the worker
    runs — the untouchable judge, ported from the Forge to the order via the event
    log. The worker's job is to make its code pass an exam it cannot edit, because
    the exam is restored from this frozen copy before it is run (see ``score``)."""
    if kind == "research":
        planned = _planner_research(brief, client) if _is_served(client) else None
        if planned:
            return {"authored_by": "planner", "checks": planned}
        return {"authored_by": "template", "checks": _template_research(brief)}
    if kind == "build" and workspace is not None:
        acc = workspace / _ACCEPTANCE_FILE
        if acc.exists():
            return {"authored_by": "operator", "checks": [
                {"type": "acceptance_test", "value": _ACCEPTANCE_FILE,
                 "content": acc.read_text()}]}
    if kind == "fetch":
        return {"authored_by": "template", "checks": [{"type": "nonempty_report", "value": ""}]}
    # No checks (a build with no acceptance test, say) → an advisory read: it scores
    # and flags but never blocks, rather than grade on a lie.
    return {"authored_by": "template", "checks": []}


def _template_research(brief: str) -> list:
    """The offline fallback rubric — brief-salient terms plus a citation check when
    the brief asks for sources. Crude by design; a served planner authors the real
    one (below)."""
    checks = [{"type": "required_fact", "value": t} for t in _salient(brief)]
    if re.search(r"\b(cite|cited|source|sources|sourced|reference)\b", brief.lower()):
        checks.append({"type": "citation"})
    return checks


def _is_served(client) -> bool:
    """True only for a real served model — the planner rubric is a model act. Offline
    and scripted stand-ins fall to the template, and never have a turn consumed."""
    if client is None:
        return False
    from mor.llm import OpenAIClient
    return isinstance(client, OpenAIClient)


def _first_json_object(text: str):
    """The first balanced ``{...}`` in text, parsed — models wrap JSON in prose."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except ValueError:
                    return None
    return None


def _planner_research(brief: str, client) -> "list | None":
    """The planner authors the acceptance rubric at ``planned``, before the work —
    the checks a correct answer must satisfy, as JSON, judging the brief rather than
    answering it. Recorded as an event, never spoken into the Hall (Wall 2). Returns
    a checks list, or None on unusable output (the caller falls to the template).

    This is the fix for V1's blank/keyword rubrics (Charge 1): the gate's exam is
    written by a mind that read the brief, not tokenized from its words."""
    prompt = (
        "You are setting the ACCEPTANCE RUBRIC for a research task, BEFORE any work is "
        "done. Read the brief and output ONLY a JSON object with keys:\n"
        '  "required_facts": [up to 5 specific claims or named entities a correct, '
        "complete answer MUST contain],\n"
        '  "forbidden_claims": [plausible but FALSE statements a wrong answer might make],\n'
        '  "require_citation": true if the answer should cite a source, else false.\n'
        "Judge the answer; do not answer it. Brief: " + brief)
    try:
        res = client.chat([{"role": "system", "content": "You author strict acceptance "
                            "rubrics as JSON, and nothing else."},
                           {"role": "user", "content": prompt}])
    except Exception:  # noqa: BLE001 — a flaky planner falls back, never crashes the order
        return None
    data = _first_json_object(res.content or "")
    if not isinstance(data, dict):
        return None
    checks = []
    for f in (data.get("required_facts") or [])[:5]:
        if isinstance(f, str) and f.strip():
            checks.append({"type": "required_fact", "value": f.strip()})
    for f in (data.get("forbidden_claims") or [])[:5]:
        if isinstance(f, str) and f.strip():
            checks.append({"type": "forbidden_claim", "value": f.strip()})
    if data.get("require_citation"):
        checks.append({"type": "citation"})
    return checks or None


# -- scoring: the vector, then the scalar ------------------------------------
_DETERMINISTIC = {
    "required_fact": "required_facts",
    "forbidden_claim": "forbidden_absent",
    "citation_substring": "citations",   # legacy: a literal substring must appear
    "citation": "citations",             # a URL or a bare domain is present
    "files_present": "files_present",
    "test_passes": "tests_pass",
    "nonempty_report": "nonempty",
}


def score(kind: str, brief: str, report: str, workspace, rubric: dict,
          client=None) -> dict:
    """Grade one artifact against its frozen rubric. Returns a FitnessVector:
    ``{vector, weights, scalar, failing, critique}``. Only the deterministic legs
    exist today — they need no model. The critic leg is a **reserved seam, not yet
    built**: its weight is pinned to 0 and ``client`` is unused. Calibration already
    measures the discrimination D that will weight it when it lands; nothing consumes
    D yet."""
    checks = (rubric or {}).get("checks", [])
    vector: dict = {}

    # The untouchable judge (build): restore each frozen acceptance test from the
    # rubric, overwriting whatever the worker left, then run it. A worker that
    # weakened its own exam is judged by the original — construction-true, exactly
    # as the Forge restores bench/ before scoring a mutant.
    acceptances = [c for c in checks if c.get("type") == "acceptance_test"]
    if acceptances and workspace is not None:
        oks = []
        for c in acceptances:
            name = c.get("value", _ACCEPTANCE_FILE)
            if c.get("content") is not None:
                (workspace / name).write_text(c["content"])
            oks.append(bench.run_acceptance(workspace, name))
        vector["acceptance"] = min(oks) if oks else 0.0

    buckets: dict = {}
    for c in checks:
        if c.get("type") == "acceptance_test":
            continue
        buckets.setdefault(c.get("type"), []).append(c.get("value", ""))

    for ctype, values in buckets.items():
        name = _DETERMINISTIC.get(ctype)
        if name == "required_facts":
            vector[name] = bench.check_required(report, values)
        elif name == "forbidden_absent":
            vector[name] = bench.check_forbidden_absent(report, values)
        elif name == "citations":
            vector[name] = (bench.check_has_citation(report) if ctype == "citation"
                            else bench.check_required(report, values))
        elif name == "files_present":
            paths = [p for v in values for p in (v if isinstance(v, list) else [v]) if p]
            vector[name] = bench.check_files_present(workspace, paths)
        elif name == "tests_pass":
            vector[name] = min(bench.check_test_passes(workspace, v) for v in values)
        elif name == "nonempty":
            vector[name] = 1.0 if (report or "").strip() else 0.0

    # The critic leg is not built yet: its weight is a placeholder 0, so it never
    # affects the scalar. Kept in the schema so the seam is visible, not pretended.
    weights = {name: 1.0 for name in vector}
    weights["critic"] = 0.0

    if not vector:
        # nothing to check (e.g. a build with a template rubric) — an honest,
        # content-only floor so the read is defined but never blocks on its own.
        vector = {"nonempty": 1.0 if (report or "").strip() else 0.0}
        weights = {"nonempty": 1.0, "critic": 0.0}

    total_w = sum(weights[n] for n in vector) or 1.0
    scalar = round(sum(vector[n] * weights[n] for n in vector) / total_w, 4)
    # A forbidden claim present is a disqualifier, not a deduction: one planted lie
    # fails the report outright — the same severity the benchmark uses (bench.py),
    # so the two graders agree on the one severity that matters.
    if vector.get("forbidden_absent") == 0.0:
        scalar = 0.0
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
    "acceptance": "the code did not pass the frozen acceptance test",
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
