"""The grimoire — the book of claims, and the one arithmetic in it that matters:
which unchecked claim, if it fell, takes the most of the map with it.

Runs with no GPU, no network. `pytest -q`.
"""

from __future__ import annotations

from mor import grimoire


def test_record_and_load_roundtrip(space):
    cid = grimoire.record_claim(space, "mor", "the loop caps faces at 8 steps",
                                "observed", test="read loop.py _MAX_STEPS")
    assert cid == "c1"
    claims = grimoire.load(space)["subjects"]["mor"]["claims"]
    assert claims["c1"]["text"] == "the loop caps faces at 8 steps"
    assert claims["c1"]["rung"] == "observed"
    assert claims["c1"]["status"] == "unchecked"
    assert claims["c1"]["test"] == "read loop.py _MAX_STEPS"
    # a second claim gets the next id, per subject
    assert grimoire.record_claim(space, "mor", "another", "inferred") == "c2"


def test_mark_updates_status_rung_and_history(space):
    cid = grimoire.record_claim(space, "mor", "x", "inferred")
    assert grimoire.mark_claim(space, "mor", cid, "held", note="checked", rung="computed")
    claim = grimoire.load(space)["subjects"]["mor"]["claims"][cid]
    assert claim["status"] == "held"
    assert claim["rung"] == "computed"
    assert len(claim["history"]) == 2  # recorded + held
    assert "checked" in claim["history"][-1]["event"]
    # a broken claim is kept, not deleted — its history holds what broke it
    grimoire.mark_claim(space, "mor", cid, "broken", note="counterexample in dome.py")
    kept = grimoire.load(space)["subjects"]["mor"]["claims"][cid]
    assert kept["status"] == "broken"
    assert "counterexample" in kept["history"][-1]["event"]


def test_mark_unknown_claim_is_refused(space):
    assert grimoire.mark_claim(space, "nope", "c9", "held") is False
    grimoire.record_claim(space, "mor", "x", "inferred")
    assert grimoire.mark_claim(space, "mor", "c9", "held") is False


def test_next_to_test_is_transitive_not_just_direct(space):
    """A diamond: c1 is the root, c2 and c3 lean on it, c4 leans on both. If c1
    is wrong the whole diamond falls — three claims — so c1 is what to test next,
    even though only two claims depend on it *directly*."""
    c1 = grimoire.record_claim(space, "mor", "the root belief", "inferred")
    c2 = grimoire.record_claim(space, "mor", "leans on root", "observed", depends_on=[c1])
    c3 = grimoire.record_claim(space, "mor", "also leans on root", "observed", depends_on=[c1])
    grimoire.record_claim(space, "mor", "leans on both", "inferred", depends_on=[c2, c3])
    best = grimoire.next_to_test(space, "mor")
    assert best["id"] == c1
    assert best["dependents"] == 3  # transitive: c2, c3, and c4 through them


def test_next_to_test_breaks_ties_to_the_older_claim(space):
    c1 = grimoire.record_claim(space, "mor", "first, no dependents", "inferred")
    grimoire.record_claim(space, "mor", "second, no dependents", "inferred")
    # both are unchecked with 0 dependents — the older (c1) wins the tie
    assert grimoire.next_to_test(space, "mor")["id"] == c1


def test_next_to_test_skips_settled_claims(space):
    c1 = grimoire.record_claim(space, "mor", "root", "observed")
    grimoire.record_claim(space, "mor", "leaf", "observed", depends_on=[c1])
    grimoire.mark_claim(space, "mor", c1, "held")
    # c1 is held now; the only thing still worth testing is the leaf
    assert grimoire.next_to_test(space, "mor")["id"] == "c2"


def test_next_to_test_across_all_subjects(space):
    grimoire.record_claim(space, "alpha", "lonely", "inferred")
    b1 = grimoire.record_claim(space, "beta", "load-bearing", "inferred")
    grimoire.record_claim(space, "beta", "d1", "observed", depends_on=[b1])
    grimoire.record_claim(space, "beta", "d2", "observed", depends_on=[b1])
    best = grimoire.next_to_test(space)  # subject=None -> scan the whole book
    assert best["subject"] == "beta" and best["id"] == b1


def test_summary_on_empty_and_populated(space):
    assert "still blank" in grimoire.summary(space)
    grimoire.record_claim(space, "mor", "the scheduler runs on names", "observed")
    s = grimoire.summary(space)
    assert "[mor]" in s and "1 unchecked" in s
    assert "the scheduler runs on names" in s  # the load-bearing claim spelled out


def test_dump_lists_subjects_then_claims(space):
    grimoire.record_claim(space, "mor", "a", "inferred")
    assert "mor (1)" in grimoire.dump(space)          # no subject -> the index
    body = grimoire.dump(space, "mor")                # named -> the claims
    assert "c1" in body and "inferred" in body
