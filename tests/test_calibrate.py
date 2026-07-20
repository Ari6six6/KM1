"""Calibration — earning the license: AUC, the θ_α cut, the power check, and the
armed-vs-advisory verdict against the seeded fixture corpus."""

from __future__ import annotations

from mor import calibrate


def test_auc_is_one_for_perfect_separation():
    assert calibrate._auc([0.9, 1.0, 0.85], [0.1, 0.4, 0.6]) == 1.0
    assert calibrate._auc([0.5], [0.5]) == 0.5            # ties are chance
    assert calibrate._auc([], [0.2]) == 0.5              # undefined → chance


def test_quantile_is_nearest_rank():
    xs = [0.2, 0.4, 0.6, 0.8, 1.0]
    assert calibrate._quantile(xs, 1.0) == 1.0
    assert calibrate._quantile(xs, 0.0) == 0.2


def test_research_corpus_separates_but_stays_advisory_on_thin_poison(project):
    # the seeded corpus discriminates perfectly (clean scores above poison)…
    ev = calibrate.calibrate_kind(project, "research", alpha=0.02, beta=0.15)
    assert ev["D"] >= 0.9
    assert ev["power_at_theta"] >= 0.9
    # …but n_poison is far below 1/alpha = 50, so the cut is noise → advisory.
    assert ev["n_poison"] < 50
    assert ev["gate"] == "advisory"


def test_a_generous_alpha_arms_the_gate_when_resolution_allows(project):
    # alpha=0.5 needs only n_poison>=2; the corpus has more and separates cleanly,
    # so the license is granted and projected for the gate to read.
    ev = calibrate.calibrate_kind(project, "research", alpha=0.5, beta=0.15)
    assert ev["gate"] == "armed"
    from mor.fitness import calibration
    cal = calibration(project, "research")
    assert cal["gate"] == "armed" and cal["theta"] == ev["theta"]


def test_build_gate_arms_offline_on_executable_truth(project):
    # build fitness is running a frozen acceptance test — no model, ever. With a
    # generous-enough alpha for the corpus size, the gate arms entirely offline.
    ev = calibrate.calibrate_kind(project, "build", alpha=0.15, beta=0.15)
    assert ev["D"] == 1.0                          # clean pass the exam, poison fail it
    assert ev["power_at_theta"] == 1.0
    assert 0.0 < ev["theta"] < 1.0                 # the cut lands in the margin
    assert ev["gate"] == "armed"


def test_build_stays_advisory_when_poison_is_too_thin_for_alpha(project):
    # same corpus, tight alpha: n_poison < 1/alpha, so the cut is noise → advisory.
    ev = calibrate.calibrate_kind(project, "build", alpha=0.02)
    assert ev["D"] == 1.0 and ev["gate"] == "advisory"


def test_missing_corpus_is_honest(project):
    ev = calibrate.calibrate_kind(project, "fetch")
    assert ev.get("error") and ev["gate"] == "advisory"


def test_calibration_writes_one_ledger_event(project):
    calibrate.calibrate_kind(project, "research")
    from mor.ledger import events
    evs = events(project, "calibration")
    assert len(evs) == 1 and evs[0]["order_kind"] == "research"
    assert "fixture_hash" in evs[0] and "n_poison" in evs[0]
