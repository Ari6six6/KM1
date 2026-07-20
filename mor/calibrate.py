"""Calibration — earning the right to block.

The Gate grades; this earns the license. A gate that blocks work must first prove,
against a corpus of *known* good and *known* poisoned reports, that its score
actually separates them — and where to place the cut. Nothing is guessed:

  D        the critic's discrimination — AUC of the score over good vs. poison.
           It is the critic leg's *weight*: a judge that can't tell a planted lie
           from an honest report is weighted 0, by law.
  θ_α      the cut. Neyman–Pearson: the (1−α) quantile of the poison scores, so at
           most a fraction α of poison clears it. α — the Master's acceptable-lie
           rate — prices the lies.
  power    the true-accept rate of *good* reports at θ_α. β — the acceptable
           retry-tax — prices the rework: the gate is licensed only if
           power ≥ 1 − β. Where the curves overlap too much to hold both α and β
           at one cut, the gate stays *advisory* — measured, honest, non-blocking.
  n        resolution. A percentile read off n poison points is noise finer than
           1/n; α = 0.02 is a promise you can only keep with ≥ 50 of them. n rides
           in the event beside θ, so a cut from thin poison carries its scar.

Every pass is one append-only event — ``{D, θ, power, α, β, n, fixture_hash,
gate}`` — and the armed cuts are also projected to ``realm/calibration.json`` for
the Gate to read. The corpus lives under ``bench/fixtures/`` and is hash-pinned
like its parent: the judge the mutant may not touch.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mor import fitness
from mor.config import gate_params, load_json, save_json
from mor.order import KINDS


def fixtures_root() -> Path:
    from mor.bench import bench_dir
    return bench_dir() / "fixtures"


def _read_set(d: Path) -> list:
    return [p.read_text() for p in sorted(d.glob("*.md"))] if d.exists() else []


def load_fixtures(kind: str) -> tuple:
    """(clean_reports, poison_reports, rubric) for a kind, or ([], [], None) if the
    corpus for it hasn't been written yet."""
    base = fixtures_root() / kind
    rubric = load_json(base / "rubric.json", None)
    return _read_set(base / "clean"), _read_set(base / "poisoned"), rubric


def _auc(pos: list, neg: list) -> float:
    """Mann–Whitney AUC: P(a good report outscores a poisoned one), ties at 0.5.
    0.5 is chance; 1.0 is perfect separation. Undefined (→ 0.5) with an empty
    side."""
    if not pos or not neg:
        return 0.5
    wins = sum((1.0 if a > b else 0.5 if a == b else 0.0) for a in pos for b in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def _quantile(xs: list, q: float) -> float:
    """The q-quantile (0..1) of xs by nearest rank — coarse on purpose: its
    resolution is 1/len(xs), which is exactly the honesty the n check enforces."""
    if not xs:
        return 1.0
    s = sorted(xs)
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return round(s[idx], 4)


def _score_all(kind: str, reports: list, rubric: dict) -> list:
    return [fitness.score(kind, "", r, None, rubric)["scalar"] for r in reports]


def _fixture_hash(kind: str) -> str:
    h = hashlib.sha256()
    base = fixtures_root() / kind
    for p in sorted(base.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(base).as_posix().encode())
            h.update(b"\0")
            h.update(p.read_bytes())
    return "sha256:" + h.hexdigest()[:16]


def calibrate_kind(project, kind: str, *, alpha=None, beta=None) -> dict:
    """One calibration pass for a kind. Scores the corpus, measures D / θ / power,
    decides armed vs advisory, records the event, and projects an armed cut into
    ``calibration.json``. Returns the event (with an ``error`` key if there is no
    corpus to practise on)."""
    params = gate_params()
    alpha = params["alpha"] if alpha is None else alpha
    beta = params["beta"] if beta is None else beta

    clean, poison, rubric = load_fixtures(kind)
    if not clean or not poison or not rubric:
        return {"kind": kind, "error": "no fixture corpus — write the poison first",
                "gate": "advisory"}

    good = _score_all(kind, clean, rubric)
    bad = _score_all(kind, poison, rubric)
    D = _auc(good, bad)
    theta = _quantile(bad, 1.0 - alpha)
    power = round(sum(1 for g in good if g >= theta) / len(good), 4) if good else 0.0
    n_poison = len(poison)

    enough = n_poison >= (1.0 / alpha if alpha > 0 else float("inf"))
    licensed = power >= (1.0 - beta) and D >= 0.5 and enough
    verdict = "armed" if licensed else "advisory"

    event = {"kind": "calibration", "order_kind": kind, "D": D, "theta": theta,
             "power_at_theta": power, "alpha": alpha, "beta": beta,
             "n_good": len(good), "n_poison": n_poison,
             "fixture_hash": _fixture_hash(kind), "gate": verdict}

    from mor.ledger import record
    record(project, "calibration", **{k: v for k, v in event.items() if k != "kind"})

    # Project the cut the Gate reads. Armed kinds carry θ/D; advisory kinds are
    # recorded too, so `mor gate` can show a measured-but-unlicensed stick.
    path = project.root / "realm" / "calibration.json"
    data = load_json(path, {})
    data[kind] = {"gate": verdict, "theta": theta, "D": D, "power": power,
                  "alpha": alpha, "beta": beta, "n_poison": n_poison,
                  "fixture_hash": event["fixture_hash"]}
    save_json(path, data)
    return event


def calibrate(project, kinds=None, *, alpha=None, beta=None) -> list:
    """Calibrate every kind (or the named ones). One event per kind."""
    return [calibrate_kind(project, k, alpha=alpha, beta=beta)
            for k in (kinds or KINDS)]
