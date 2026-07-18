"""The think→act loop and its guards."""

from __future__ import annotations

from mor.loop import think_and_act, _REFLECT_NUDGE
from mor.llm import ScriptClient, MockClient, Client, ChatResult, ToolCall, cut_loops
from mor.tools import ToolContext, build_tools


def _ctx(project, can_egress=False):
    ws = project.workspace
    ws.mkdir(parents=True, exist_ok=True)
    return ToolContext(workspace=ws, project=project, can_egress=can_egress)


def test_loop_executes_a_tool_and_grounds_the_answer(project):
    ctx = _ctx(project)
    (ctx.workspace / "note.txt").write_text("the east ford is out")
    client = ScriptClient([
        {"tool": "read_file", "args": {"path": "note.txt"}},
        {"text": "The east ford is out; route north."},
    ])
    line, tainted = think_and_act(
        client, system="s", user="read note.txt",
        tools=build_tools(["read_file"], ctx), ctx=ctx)
    assert "north" in line
    assert tainted is False


def test_offline_mock_runs_the_loop_and_speaks(project):
    ctx = _ctx(project)
    line, _ = think_and_act(
        MockClient(), system="s", user="u", tools=build_tools(["read_file"], ctx),
        ctx=ctx, seed="I am ready.")
    assert line == "I am ready."


def test_reflect_reflex_pushes_to_think(project):
    ctx = _ctx(project)
    (ctx.workspace / "f").write_text("x")

    class Capture(Client):
        def __init__(self):
            self.last = []

        def chat(self, messages, tools=None):
            self.last = list(messages)
            acted = sum(1 for m in messages if m.get("role") == "tool")
            if acted < 3:
                return ChatResult(content=None,
                                  tool_calls=[ToolCall("c", "read_file", '{"path": "f"}')])
            return ChatResult(content="done")

    b = Capture()
    think_and_act(b, system="s", user="u", tools=build_tools(["read_file"], ctx), ctx=ctx)
    assert any(m.get("content") == _REFLECT_NUDGE for m in b.last)


def test_loop_terminates_at_the_step_budget(project):
    ctx = _ctx(project)
    (ctx.workspace / "f").write_text("x")

    class Forever(Client):
        def chat(self, messages, tools=None):
            return ChatResult(content="thinking",
                              tool_calls=[ToolCall("c", "read_file", '{"path": "f"}')])

    line, _ = think_and_act(Forever(), system="s", user="u",
                            tools=build_tools(["read_file"], ctx), ctx=ctx, max_steps=4)
    assert line  # it always says something rather than looping forever


def test_cut_loops_trims_runaway_repetition():
    spun = "The gate is shut. " * 5
    out = cut_loops(spun)
    assert "repeat loop trimmed" in out
    assert out.count("The gate is shut.") < 5   # the runaway loop is cut back


def test_cut_loops_leaves_honest_text_alone():
    ok = "First point. Second point. Third and final point."
    assert cut_loops(ok) == ok
