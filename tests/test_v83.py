"""The Thirteenth — the Dreaming — and the Cathedral that renders the realm.

The dream is real graph reasoning: it must find a missing edge the realm's own
knowledge implies, turn over a load-bearing belief, and seed its questions into
the next dawn's grimoire. The Cathedral must fold the whole realm into one
self-contained page without crashing on a sparse realm or inventing anything.
"""

from __future__ import annotations

from mor import dream, grimoire, ontology, vision, world


# --- the dream: real link prediction over the graph --------------------------
class TestDreaming:
    def _seed_graph(self, space):
        conn = ontology.connect(space)
        # A—B and B—C and A—B2, C—B2 all present, but A—C never asserted: the
        # dream must propose that missing edge.
        ontology.relate(conn, "Warrior", "uses", "Vast")
        ontology.relate(conn, "Vast", "provides", "GPU")
        ontology.relate(conn, "Wizard", "uses", "Vast")
        ontology.relate(conn, "Wizard", "keeps", "Grimoire")
        conn.close()

    def test_bridge_finds_a_missing_edge(self, space):
        self._seed_graph(space)
        rec = dream.dream(space, backend=None, day=1)
        kinds = [v["kind"] for v in rec["visions"]]
        assert "bridge" in kinds
        bridge = next(v for v in rec["visions"] if v["kind"] == "bridge")
        # the two things it bridged share a neighbour but are not directly linked
        assert bridge["seed"] and "bridged through" in bridge["seed"]["text"]

    def test_negation_turns_over_a_load_bearing_claim(self, space):
        c1 = grimoire.record_claim(space, "gate", "the rail blocks private IPs", "inferred")
        grimoire.record_claim(space, "gate", "safe to open wide", "inferred", depends_on=[c1])
        rec = dream.dream(space, backend=None, day=2)
        neg = [v for v in rec["visions"] if v["kind"] == "negation"]
        assert neg and "the rail blocks private IPs" in neg[0]["text"]

    def test_dream_is_deterministic_offline(self, space):
        self._seed_graph(space)
        a = dream.dream(space, backend=None, day=1)
        b = dream.dream(space, backend=None, day=1)
        assert [v["text"] for v in a["visions"]] == [v["text"] for v in b["visions"]]
        assert a["how"] == "hashed"

    def test_seed_into_dawn_writes_the_questions_into_the_grimoire(self, space):
        self._seed_graph(space)
        dream.dream(space, backend=None, day=3)
        before = grimoire.load(space).get("subjects", {})
        assert "the dreaming" not in before
        rec = dream.seed_into_dawn(space, 3)
        assert rec.get("seeded")                       # ids came back
        after = grimoire.load(space)["subjects"]["the dreaming"]["claims"]
        assert after                                    # the realm's own question, now a claim
        # and it is unproven, so the General's audit will surface it at dawn
        best = grimoire.next_to_test(space)
        assert best is not None

    def test_a_quiet_realm_dreams_honestly(self, space):
        rec = dream.dream(space, backend=None, day=1)
        assert rec["visions"] == []
        assert "without a dream" in rec["woven"]
        assert dream.render_line(rec) == ""             # nothing to speak

    def test_dream_never_calls_a_non_served_backend(self, space):
        # dusk uses ScriptBackend/MockBackend — the dream must not consume a turn.
        self._seed_graph(space)

        class Boom:
            def chat(self, *a, **k):
                raise AssertionError("the dream must not call chat() offline")

        rec = dream.dream(space, backend=Boom(), day=1)
        assert rec["how"] == "hashed" and rec["visions"]


# --- the Cathedral: the realm renders itself ---------------------------------
class TestCathedral:
    def test_renders_self_contained_page(self, space):
        conn = ontology.connect(space)
        ontology.relate(conn, "Warrior", "uses", "Vast")
        ontology.relate(conn, "Vast", "provides", "GPU")
        conn.close()
        grimoire.record_claim(space, "mor", "a belief", "inferred")
        world.record_sortie(space, "example.com", "GET 200", ips=["203.0.113.5"], path="/")
        html = vision.render(space, standalone=True)
        assert html.startswith("<!doctype html>")
        assert "The Constellation" in html and "<svg" in html
        # self-contained: nothing is fetched from off-page
        assert "https://" not in html
        assert "<script src" not in html and "<link" not in html
        assert "@import" not in html and "url(http" not in html

    def test_empty_realm_renders_without_crashing(self, space):
        html = vision.render(space, standalone=True)
        assert "Cathedral" in html and "constellation is dark" in html

    def test_layout_is_deterministic(self, space):
        names = ["a", "b", "c", "d"]
        edges = [("a", "b"), ("b", "c")]
        p1 = vision._layout(names, edges, 400, 300)
        p2 = vision._layout(names, edges, 400, 300)
        assert p1 == p2 and all(0 <= x <= 400 and 0 <= y <= 300 for x, y in p1.values())

    def test_write_produces_a_file(self, space, tmp_path):
        out = tmp_path / "cathedral.html"
        p = vision.write(space, out)
        assert p == out and out.exists() and out.read_text().startswith("<!doctype")
