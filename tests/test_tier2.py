"""Tier 2 — three more Evangelisms, pinned.

The Third (the shelf: how-to notes the realm loads only when needed), the Sixth
(checkpointing: the space set aside before the realm rewrites it, restorable),
and the Seventh (verification enforcement: a file-changing turn that ran no
check is bounced once — run one, or name the work unverified).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from mor import checkpoint, skills, world
from mor.config import mor_home
from mor.engine import ScriptBackend, ToolContext, default_tools, think_and_act
from mor.engine.backend import Backend, ChatResult, ToolCall
from mor.engine.tools import _skill_load, _skill_record
from mor.realm import Realm


def _ctx(space, tmp_path, embodied=False):
    dome = SimpleNamespace(embodied=True, exec=lambda role, cmd: (0, "ok", "")) \
        if embodied else None
    return ToolContext(workspace=tmp_path, space=space, can_egress=False,
                       tainted=[], dome=dome, role="wizard")


# --- the Third: the shelf -----------------------------------------------------
def test_a_skill_is_recorded_indexed_and_loaded(space, tmp_path):
    ctx = _ctx(space, tmp_path)
    assert "recorded" in _skill_record(
        {"name": "serve-glm", "body": "# Serving GLM\nAlways tunnel 18080 first."}, ctx)
    body = _skill_load({"name": "serve-glm"}, ctx)
    assert "tunnel 18080" in body
    assert "serve-glm — Serving GLM" in skills.index(space)
    assert "no skill 'missing'" in _skill_load({"name": "missing"}, ctx)


def test_skill_names_are_validated(space, tmp_path):
    ctx = _ctx(space, tmp_path)
    assert _skill_record({"name": "../evil", "body": "x"}, ctx).startswith("ERROR")
    assert _skill_record({"name": "ok", "body": ""}, ctx).startswith("ERROR")


def test_the_spaces_own_shelf_overrides_the_global(space, tmp_path):
    g = mor_home() / "skills"
    g.mkdir(parents=True)
    (g / "shared.md").write_text("# Global way\nfrom the global shelf\n")
    (g / "only-global.md").write_text("# Global only\n")
    ctx = _ctx(space, tmp_path)
    _skill_record({"name": "shared", "body": "# Space way\nthis realm's own\n"}, ctx)
    assert "Space way" in _skill_load({"name": "shared"}, ctx)      # space wins
    assert "Global only" in _skill_load({"name": "only-global"}, ctx)  # global crosses over


def test_the_shelf_index_rides_the_volatile_turn(space):
    from mor.agents import line

    class Cap(Backend):
        def __init__(self):
            self.users = []

        def chat(self, messages, tools=None):
            self.users.append(messages[1]["content"])
            return ChatResult(content="ok")

    skills.record(space, "serve-glm", "# Serving GLM\nTunnel first.")
    b = Cap()
    line(b, space, "wizard", "wake", hall_tail="")
    assert "serve-glm — Serving GLM" in b.users[0]
    assert "Serving GLM\nTunnel" not in b.users[0]  # the index, never the body


# --- the Sixth: checkpointing --------------------------------------------------
def test_snapshot_and_restore_rewinds_the_space(space):
    f = space.root / "gate.json"
    f.write_text('{"domains": ["a.example"]}')
    sid = checkpoint.snapshot(space, "before")
    assert sid and sid in checkpoint.list_snapshots(space)
    f.write_text('{"domains": ["changed.example"]}')
    ok, msg = checkpoint.restore(space, sid)
    assert ok and sid in msg
    assert json.loads(f.read_text())["domains"] == ["a.example"]
    # the rail never burns the present: a pre-restore snapshot was taken too
    assert any("pre-restore" in s for s in checkpoint.list_snapshots(space))


def test_restore_refuses_unknown_ids(space):
    ok, msg = checkpoint.restore(space, "not-a-snapshot")
    assert not ok and "not a snapshot id" in msg
    ok, msg = checkpoint.restore(space, "20260101-000000-000001-ghost")
    assert not ok and "no snapshot" in msg


def test_only_the_last_few_snapshots_are_kept(space, monkeypatch):
    monkeypatch.setattr(checkpoint, "_KEEP", 2)
    for label in ("one", "two", "three", "four"):
        checkpoint.snapshot(space, label)
    snaps = checkpoint.list_snapshots(space)
    assert len(snaps) == 2 and snaps[0].endswith("three") and snaps[1].endswith("four")


def test_dawn_and_dusk_keep_their_own_snapshots(space, monkeypatch):
    monkeypatch.setattr("mor.engine.dome.probe_runtime", lambda: "")
    r = Realm(space, echo=False)
    r.light()
    assert any(s.endswith(f"day{r.day}-dawn") for s in checkpoint.list_snapshots(space))
    r.dark()
    assert any(s.endswith("-dusk") for s in checkpoint.list_snapshots(space))


def test_restore_is_refused_while_the_realm_is_awake(space, monkeypatch, capsys):
    from mor.cli import _dispatch
    monkeypatch.setattr("mor.engine.dome.probe_runtime", lambda: "")
    (space.root / "gate.json").write_text('{"domains": ["original.example"]}')
    r = Realm(space, echo=False)
    r.light()
    sid = checkpoint.snapshot(space, "x")
    assert _dispatch(r, f"checkpoint restore {sid}") is True
    assert "seal the day" in capsys.readouterr().out  # refused while awake
    r.dark()
    capsys.readouterr()  # clear the day's output
    (space.root / "gate.json").write_text('{"domains": ["mutated.example"]}')
    assert _dispatch(r, f"checkpoint restore {sid}") is True
    assert json.loads((space.root / "gate.json").read_text())["domains"] == \
        ["original.example"]


# --- the Seventh: verification enforcement --------------------------------------
class RecBackend(Backend):
    """Plays a script and remembers every call's messages."""

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

    def saw_seventh(self):
        """How many times the Seventh's nudge was INJECTED (the newest user
        message of a call) — history quoting it later doesn't count."""
        n = 0
        for msgs in self.calls:
            users = [m["content"] for m in msgs if m["role"] == "user"]
            if users and "Seventh" in users[-1]:
                n += 1
        return n


def _turn(backend, ctx):
    return think_and_act(backend, role="wizard", kind="sortie", heard="do it",
                         system="sys", user="task", tools=default_tools(ctx), ctx=ctx)


def test_a_file_changing_turn_with_no_check_is_bounced_once(space, tmp_path):
    ctx = _ctx(space, tmp_path, embodied=True)
    b = RecBackend([
        {"tool": "write_file", "args": {"path": "a.py", "content": "print(1)"}},
        {"text": "Done — it should work."},          # ← bounced here, once
        {"tool": "run_shell", "args": {"command": "python3 a.py"}},
        {"text": "Checked — it runs."},
    ])
    spoken, _ = _turn(b, ctx)
    assert spoken == "Checked — it runs."
    assert b.saw_seventh() == 1


def test_a_checked_turn_is_never_bounced(space, tmp_path):
    ctx = _ctx(space, tmp_path, embodied=True)
    b = RecBackend([
        {"tool": "write_file", "args": {"path": "a.py", "content": "print(1)"}},
        {"tool": "run_shell", "args": {"command": "python3 a.py"}},
        {"text": "Written and checked."},
    ])
    spoken, _ = _turn(b, ctx)
    assert spoken == "Written and checked."
    assert b.saw_seventh() == 0


def test_a_disembodied_face_is_never_bounced(space, tmp_path):
    ctx = _ctx(space, tmp_path, embodied=False)  # no run_shell in the toolbox
    b = RecBackend([
        {"tool": "write_file", "args": {"path": "note.md", "content": "words"}},
        {"text": "A note, nothing to run."},
    ])
    spoken, _ = _turn(b, ctx)
    assert spoken == "A note, nothing to run."
    assert b.saw_seventh() == 0


def test_the_bounce_fires_only_once(space, tmp_path):
    ctx = _ctx(space, tmp_path, embodied=True)
    b = RecBackend([
        {"tool": "write_file", "args": {"path": "a.py", "content": "x"}},
        {"text": "Still not checking."},   # bounced once...
        {"text": "Says it plainly instead."},  # ...never twice
    ])
    spoken, _ = _turn(b, ctx)
    assert spoken == "Says it plainly instead."
    assert b.saw_seventh() == 1
