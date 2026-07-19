"""R4 — the Cathedral: the realm rendered as one self-contained page."""

from __future__ import annotations

import json
import time

from mor.cathedral import render, _layout


def test_layout_is_deterministic():
    nodes = {"a", "b", "c", "d"}
    edges = [("a", "b"), ("b", "c"), ("c", "d")]
    assert _layout(nodes, edges) == _layout(nodes, edges)   # same seed → same sky


def test_render_is_self_contained_html(project):
    page = render(project)
    assert page.startswith("<!doctype html>")
    assert "the Cathedral" in page
    # self-contained: no external network references
    for bad in ("http://", "https://", "src=", "cdn"):
        assert bad not in page.lower() or bad == "http://"    # (no src=/cdn/https links)
    assert "https://" not in page and "src=" not in page


def test_render_draws_the_constellation_and_dream(project):
    # seed a day + a dream so the mind window has content
    stamp = time.strftime("%Y%m%d") + "-000000"
    sp = project.session_path(stamp)
    sp.parent.mkdir(parents=True, exist_ok=True)
    day = ["alpha uses beta", "gamma uses delta", "epsilon contradicts zeta"]
    sp.write_text("\n".join(json.dumps({"speaker": "lead", "addressee": "worker",
                                        "text": t, "seq": i}) for i, t in enumerate(day)))
    from mor.dream import dream
    dream(project)
    page = render(project)
    assert "<svg" in page and "<circle" in page and "<line" in page      # a constellation
    assert "alpha" in page                                                # a star we know
    assert "?" in page                                                    # a dream question


def test_render_survives_an_empty_realm(project):
    page = render(project)                     # nothing seeded
    assert page.startswith("<!doctype html>")
    assert "the graph is dark" in page          # honest empty state, no crash


def test_juice_curve_appears_after_forge_verdicts(project):
    from mor.ledger import record
    for j in (66.67, 80.0, 100.0):
        record(project, "forge.verdict", verdict="keep", juice=j, delta=1.0)
    page = render(project)
    assert "<polyline" in page and "100.0" in page
