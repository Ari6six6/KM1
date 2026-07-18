"""Tier 3 — the last three Evangelisms, pinned. All nine now lit.

The First (standing directives: the Master's word that holds every turn),
the Fourth (subagent delegation: a clean pair of hands with a narrow brief),
and the Ninth (retrospection: at dusk the Wizard keeps what the day taught).
"""

from __future__ import annotations

import json

import pytest

from mor import directives, skills
from mor.engine import ScriptBackend, ToolContext, default_tools, think_and_act
from mor.engine.backend import Backend, ChatResult, ToolCall
from mor.engine.tools import _delegate
from mor.realm import Realm


# --- the First: standing directives -------------------------------------------
def test_directives_set_list_and_lift(space):
    idx, warn = directives.add(space, "never use curl")
    assert idx == 1 and warn is None
    idx, warn = directives.add(space, "always show the numbers")
    assert idx == 2
    assert directives.summary(space) == \
        "1. never use curl; 2. always show the numbers"
    assert directives.drop(space, 1)
    assert "always show" in directives.summary(space)
    assert not directives.drop(space, 9)


def test_an_exact_duplicate_is_refused(space):
    directives.add(space, "never  use   curl")
    idx, warn = directives.add(space, "never use curl")
    assert "already stands" in warn
    assert len(directives.all(space)) == 1


def test_a_near_duplicate_is_flagged_for_reconciliation(space):
    directives.add(space, "never use curl for fetches")
    idx, warn = directives.add(space, "never use curl for sorties")
    assert warn and "directive 1" in warn
    assert len(directives.all(space)) == 2  # the Master is sovereign — both stand


def test_the_standing_word_rides_every_turn(space):
    from mor.agents import line

    class Cap(Backend):
        def __init__(self):
            self.users = []

        def chat(self, messages, tools=None):
            self.users.append(messages[1]["content"])
            return ChatResult(content="ok")

    b = Cap()
    line(b, space, "general", "wake", hall_tail="")
    assert "standing directives" not in b.users[0]  # nothing stands yet
    directives.add(space, "never use curl")
    line(b, space, "general", "wake", hall_tail="")
    assert "1. never use curl" in b.users[1]


def test_direct_command_sets_lists_and_lifts(space, monkeypatch, capsys):
    from mor.cli import _dispatch
    monkeypatch.setattr("mor.engine.dome.probe_runtime", lambda: "")
    r = Realm(space, echo=False)
    assert _dispatch(r, "direct never use curl") is True
    assert directives.summary(space) == "1. never use curl"
    assert _dispatch(r, "direct") is True
    assert "never use curl" in capsys.readouterr().out
    assert _dispatch(r, "direct drop 1") is True
    assert directives.all(space) == []


# --- the Fourth: a clean pair of hands ----------------------------------------
class RecBackend(Backend):
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append(list(messages))
        step = self.script.pop(0)
        if "tool" in step:
            return ChatResult(tool_calls=[
                ToolCall("c1", step["tool"], json.dumps(step.get("args", {})))])
        return ChatResult(content=step["text"])


def _ctx(space, tmp_path, **kw):
    return ToolContext(workspace=tmp_path, space=space, can_egress=False,
                       tainted=[], role="wizard", **kw)


def test_a_delegation_runs_a_clean_child_and_reports_back(space, tmp_path):
    ctx = _ctx(space, tmp_path)
    b = RecBackend([
        {"tool": "delegate", "args": {"task": "check the gate"}},
        {"text": "the gate stands open"},               # the child's report
        {"text": "Master — the gate stands open."},     # the parent's line
    ])
    ctx.backend = b
    spoken, _ = think_and_act(b, role="wizard", kind="sortie", heard="check it",
                              system="the parent voice", user="the task",
                              tools=default_tools(ctx), ctx=ctx)
    assert spoken == "Master — the gate stands open."
    child_call = b.calls[1]
    assert "clean pair of hands" in child_call[0]["content"]
    assert "The Hall so far" not in child_call[0]["content"]  # the child is clean
    assert ctx.delegations == 1


def test_hands_dont_grow_hands(space, tmp_path):
    ctx = _ctx(space, tmp_path, depth=1)
    names = {t.name for t in default_tools(ctx)}
    assert "delegate" not in names


def test_the_turns_hands_are_bounded(space, tmp_path):
    ctx = _ctx(space, tmp_path)
    ctx.backend = RecBackend([])
    ctx.delegations = 3
    assert "enough hands" in _delegate({"task": "one more"}, ctx)


def test_a_check_the_child_ran_counts_for_the_turn(space, tmp_path):
    from types import SimpleNamespace
    ctx = _ctx(space, tmp_path,
               dome=SimpleNamespace(embodied=True, exec=lambda r, c: (0, "ok", "")))
    b = RecBackend([
        {"tool": "run_shell", "args": {"command": "true"}},
        {"text": "checked and sound"},
    ])
    ctx.backend = b
    report = _delegate({"task": "verify it"}, ctx)
    assert report == "checked and sound"
    assert ctx.checked is True  # the Seventh counts the child's check


# --- the Ninth: retrospection at dusk ------------------------------------------
def _dark_script(retro_steps):
    # 3 faces × (inside + outside walls), then the Chant, then the retrospect beat
    return [{"text": "a wall"}] * 6 + [{"text": "the chant"}] + retro_steps


def _day_hall(space, day=1):
    """The sealed day's Hall, read from disk (dark() lets its Hall object go)."""
    from mor.hall import Hall
    return Hall(space, day, echo=False).entries()


def test_dusk_ends_with_the_wizard_looking_back(space, monkeypatch):
    monkeypatch.setattr("mor.engine.dome.probe_runtime", lambda: "")
    r = Realm(space, echo=False)
    r.light()
    r.backend = ScriptBackend(_dark_script([{"text": "The day taught nothing new."}]))
    r.dark()
    last = _day_hall(space)[-1]
    assert (last["speaker"], last["addressee"]) == ("wizard", None)
    assert last["text"] == "The day taught nothing new."


def test_the_shelf_grows_by_the_realms_own_hand(space, monkeypatch):
    monkeypatch.setattr("mor.engine.dome.probe_runtime", lambda: "")
    r = Realm(space, echo=False)
    r.light()
    r.backend = ScriptBackend(_dark_script([
        {"tool": "skill_record",
         "args": {"name": "dawn-lesson", "body": "# Dawn lesson\nCheck the gate first."}},
        {"text": "I kept one lesson on the shelf."},
    ]))
    r.dark()
    assert "Check the gate first" in skills.load(space, "dawn-lesson")
    assert skills.index(space).startswith("dawn-lesson")
