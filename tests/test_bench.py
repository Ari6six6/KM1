"""R3a — the Benchmarks: a deterministic, hash-pinned, isolated judge."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mor import bench


def test_suite_scores_green_and_is_deterministic():
    a = bench.run_suite(verify=False)
    b = bench.run_suite(verify=False)
    assert a["score"] == b["score"]            # twice identical (acceptance #1)
    assert a["tasks"] >= 6                      # ≥6 tasks shipped
    assert a["score"] >= 80.0                   # the baseline is green on day one
    kinds = {row["kind"] for row in a["breakdown"]}
    assert {"research", "build", "recall"} <= kinds


def test_every_task_passes_at_baseline():
    for row in bench.run_suite(verify=False)["breakdown"]:
        assert row["score"] >= 0.999, f"{row['id']} is not green: {row['score']}"


def test_compute_manifest_detects_a_changed_file():
    m1 = bench.compute_manifest()
    probe = bench.repo_root() / "bench" / "tasks" / "_tamper_probe.tmp"
    probe.write_text("x")
    try:
        assert bench.compute_manifest() != m1   # a tamper changes the fingerprint
    finally:
        probe.unlink()
    assert bench.compute_manifest() == m1        # removed → back to the original


def test_run_suite_refuses_on_a_manifest_mismatch(monkeypatch):
    monkeypatch.setattr(bench, "verify_manifest", lambda: False)
    with pytest.raises(RuntimeError):
        bench.run_suite()                        # verify=True default → refuses (acceptance #2)


def test_run_suite_runs_when_the_manifest_is_good(monkeypatch):
    monkeypatch.setattr(bench, "verify_manifest", lambda: True)
    assert bench.run_suite()["score"] >= 80.0


def test_bench_leaves_no_trace_in_the_real_mor_home(project):
    home = Path(os.environ["MOR_HOME"])
    before = set(home.rglob("*"))
    bench.run_suite(verify=False)                # runs in throwaway temp homes
    assert set(home.rglob("*")) == before        # zero trace (acceptance #3)


def test_pin_roundtrips(monkeypatch, tmp_path):
    # pin writes the current fingerprint; verify then matches — without touching
    # the repo's real manifest (redirect it to a temp file)
    fake = tmp_path / "MANIFEST.sha256"
    monkeypatch.setattr(bench, "manifest_path", lambda: fake)
    digest = bench.pin()
    assert fake.read_text().strip() == digest
    assert bench.verify_manifest() is True
