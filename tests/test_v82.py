"""The Twelfth Evangelism, proven: the Muzzle (repetition cut at the source),
the one-breath budget, the identical-call loop guard, and the silence rule."""

from __future__ import annotations

from mor import agents
from mor.engine import ScriptBackend, ToolContext, think_and_act
from mor.engine.loop import _cut_repetition


# The actual loop from Day 5's Chant, verbatim.
CHANT_LOOP = ("I am awake, eyes on the grimoir and the chant — the map of the "
              "outside remains blank, no ground has returned from the Warrior. " * 12)


class CaptureBackend(ScriptBackend):
    def __init__(self, script):
        super().__init__(script)
        self.seen = []

    def chat(self, messages, tools=None):
        self.seen.append(" || ".join(str(m.get("content", "")) for m in messages))
        return super().chat(messages, tools)


class TestRepetitionCut:
    def test_sentence_loop_cut_once(self):
        out = _cut_repetition(CHANT_LOOP)
        assert out.count("I am awake, eyes on the grimoir") == 1
        assert "repeated itself" in out
        assert len(out) < 300

    def test_two_mentions_is_not_a_loop(self):
        text = ("The gate stays shut. We checked it twice. "
                "The gate stays shut. So we moved on.")
        assert _cut_repetition(text) == text

    def test_word_period_loop_cut(self):
        text = ("the warrior checked the gate and found it closed tight "
                * 5) + "and then he reported"
        out = _cut_repetition(text)
        assert "repeated itself" in out
        assert out.count("the warrior checked the gate and found it closed tight") == 1

    def test_filler_words_do_not_trigger(self):
        text = "It was very very very very cold that night, and the watch changed."
        assert _cut_repetition(text) == text

    def test_normal_report_untouched(self):
        text = ("Read core.py and found the bug in the retry path. "
                "Fixed it and ran the suite: green. One claim marked held.")
        assert _cut_repetition(text) == text


class TestCallLoopGuard:
    def test_identical_calls_get_one_nudge(self, space):
        call = {"tool": "search_workspace", "args": {"pattern": "gate"}}
        backend = CaptureBackend([call, call, call, call, {"text": "done"}])
        ctx = ToolContext(workspace=space.root / "w", space=space, role="wizard")
        think_and_act(backend, role="wizard", kind="wake", heard="", system="s",
                      user="u", tools=[], ctx=ctx, max_steps=8)
        # the nudge was injected exactly ONCE (it then rides the transcript —
        # so count occurrences in the final snapshot, not across snapshots)
        assert backend.seen[-1].count("exact same tool call") == 1


class TestOneBreath:
    def test_chant_budget(self):
        out = agents._budget_line("chant", "word " * 400)
        assert len(out) <= 750 and "kept brief" in out

    def test_wake_budget_tighter(self):
        out = agents._budget_line("wake", "word " * 400)
        assert len(out) <= 500 and "kept brief" in out

    def test_council_line_under_budget_untouched(self):
        text = "Short report. " * 20
        assert agents._budget_line("council_from_general", text) == text

    def test_chant_loop_never_reaches_the_hall(self, space):
        backend = ScriptBackend([{"text": CHANT_LOOP}])
        spoken = agents.line(backend, space, "wizard", "chant")
        assert spoken.count("I am awake, eyes on the grimoir") == 1
        assert len(spoken) <= 750

    def test_silence_rule_is_law(self, space):
        system = agents._build_system(space, "general")
        assert "TEN WORDS OR FEWER" in system
        assert "ONE BREATH" in system
