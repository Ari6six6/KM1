"""v7 — stability: the guards that keep a small mind from poisoning the realm.

Four failures seen in the wild, four fixes pinned here:
  1. runaway generation — a wake line looped ("The Warrior will report this to
     the General…" hundreds of times) and the megabyte line landed in the Hall,
     poisoning every prompt after it → cut_loops + repeat_penalty + Hall cap.
  2. silence — a face returned an empty line and the Hall recorded "(said
     nothing)" → one nudge before silence is accepted.
  3. a blind court — the General asked the Master whether a colony stands that
     stood already → the live frontier rides every turn's context.
  4. inverted authority — the grimoire's claim machinery was turned on the
     Master's own word → the Laws of Truth in the roster.
"""

from __future__ import annotations

from mor import agents
from mor.engine.backend import ChatResult, ServedBackend, cut_loops
from mor.engine.loop import think_and_act
from mor.engine.tools import ToolContext
from mor.hall import Hall

LOOP_SENTENCE = "The Warrior will report this to the General and wait for further orders."


# -- 1. the loop guard -------------------------------------------------------
def test_cut_loops_stops_the_warriors_megaloop():
    # as seen in the wild: an honest preamble, then one sentence repeated forever
    wild = ("I am ready, Warrior. I see the shelf is empty. "
            + (LOOP_SENTENCE + " ") * 300)
    cut = cut_loops(wild)
    assert "the line ran wild" in cut
    assert len(cut) < 500
    assert cut.count(LOOP_SENTENCE) == 1          # the first occurrence stands
    assert cut.startswith("I am ready, Warrior.")  # the honest preamble survives


def test_cut_loops_leaves_honest_speech_alone():
    normal = ("I checked the colony ground: three files, all tests pass. "
              "The claim held. I report to the General.")
    assert cut_loops(normal) == normal
    # short repeated sentences are emphasis, not a loop
    emphasis = "No. No. No. The gate stays shut."
    assert cut_loops(emphasis) == emphasis
    # a long sentence said twice is an echo, not a loop — the bar is three
    twice = f"{LOOP_SENTENCE} {LOOP_SENTENCE}"
    assert cut_loops(twice) == twice


def test_cut_loops_catches_a_punctuation_free_tail():
    unit = "loopsegment-no-punctuation "
    wild = "the report begins well enough " + unit * 60
    cut = cut_loops(wild)
    assert "the line ran wild" in cut
    assert cut.count(unit.strip()) == 1


class _FakePost(ServedBackend):
    """A served mind with the wire swapped out: captures the body it would
    send and answers with a canned payload."""

    def __init__(self, state, content):
        super().__init__(state)
        self._content = content
        self.sent_body = None

    def _post(self, body):
        self.sent_body = body
        return {"choices": [{"message": {"content": self._content}}]}


def test_served_mind_sends_repeat_penalty_and_cuts_wild_lines():
    state = {"base_url": "http://oracle", "model": "glm"}
    wild = ("Ready. " + LOOP_SENTENCE + " ") * 50
    b = _FakePost(state, wild)
    res = b.chat([{"role": "user", "content": "wake"}])
    assert b.sent_body["repeat_penalty"] == 1.1   # the sampler leans against loops
    assert "the line ran wild" in res.content     # and the guard cuts what leaks
    state2 = {"base_url": "http://oracle", "sampling": {"repeat_penalty": 1.3}}
    assert _FakePost(state2, "ok").repeat_penalty == 1.3  # the Master's override


# -- 2. the Hall cap ---------------------------------------------------------
def test_hall_caps_a_wild_line(space):
    h = Hall(space, 1, echo=False)
    h.post("warrior", "general", "x" * 6000)
    entry = h.entries()[-1]
    assert len(entry["text"]) < 1600
    assert entry["text"].endswith("the Hall cut it)")
    # an ordinary line passes untouched
    h.post("general", None, "a plain line")
    assert h.entries()[-1]["text"] == "a plain line"


# -- 3. the empty-line nudge -------------------------------------------------
class _EmptyThenLine:
    def __init__(self):
        self.calls = 0
        self.user_messages = []

    def chat(self, messages, tools=None):
        self.calls += 1
        self.user_messages += [m["content"] for m in messages if m["role"] == "user"]
        if self.calls == 1:
            return ChatResult(content="")
        return ChatResult(content="the real line")


class _AlwaysEmpty:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        return ChatResult(content="")


def _ctx(space, backend):
    return ToolContext(workspace=space.root, space=space, dome=None,
                       role="wizard", backend=backend)


def test_an_empty_answer_gets_one_nudge(space):
    b = _EmptyThenLine()
    spoken, _ = think_and_act(b, role="wizard", kind="wake", heard="",
                              system="s", user="u", tools=[], ctx=_ctx(space, b))
    assert spoken == "the real line"
    assert any("You said nothing" in m for m in b.user_messages)


def test_endless_silence_still_terminates(space):
    b = _AlwaysEmpty()
    spoken, _ = think_and_act(b, role="wizard", kind="wake", heard="",
                              system="s", user="u", tools=[], ctx=_ctx(space, b))
    assert spoken == "(said nothing)"
    assert b.calls == 2  # one try, one nudge, then the silence is accepted


# -- 4. the court sees the frontier ------------------------------------------
class _FakeDome:
    def __init__(self, living):
        self._living = living

    def colonies(self):
        return self._living


def test_volatile_carries_the_live_frontier(space):
    space.dome = _FakeDome(["sunflowervalley"])
    volatile = agents._build_volatile(space, "")
    assert "sunflowervalley" in volatile
    assert "standing NOW" in volatile
    space.dome = _FakeDome([])
    assert "no colony stands" in agents._build_volatile(space, "")
    del space.dome
    assert "no colony stands" in agents._build_volatile(space, "")


# -- 5. the laws of truth ------------------------------------------------------
def test_the_roster_lays_down_the_law():
    assert "The Master's word is ground truth" in agents.ROSTER
    assert "Never invent a report" in agents.ROSTER
    assert "memory can be stale" in agents.ROSTER
