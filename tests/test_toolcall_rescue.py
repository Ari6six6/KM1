"""Charge 2 — a model that writes its tool calls as prose gets them rescued and
executed, so a turn never ends on an unrun promise. Charge 6 — the crew's tool
use is recorded as events, not just its spoken lines."""

from __future__ import annotations

from mor.llm import Client, ChatResult, parse_prose_tool_calls
from mor.loop import think_and_act
from mor.tools import ToolContext, build_tools
from mor.order import run_order


def test_parse_prose_tool_calls_glm_xml_flavor():
    text = ("I'll run the test now.<tool_call>read_file<arg_key>path</arg_key>"
            "<arg_value>test_x.py</arg_value></tool_call>")
    cleaned, calls = parse_prose_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert '"path": "test_x.py"' in calls[0].arguments
    assert "<tool_call>" not in cleaned and cleaned.startswith("I'll run the test")


def test_parse_prose_tool_calls_json_flavor_and_none():
    _, calls = parse_prose_tool_calls('<tool_call>{"name": "list_dir", "arguments": {}}</tool_call>')
    assert len(calls) == 1 and calls[0].name == "list_dir"
    assert parse_prose_tool_calls("no calls here, just prose") == ("no calls here, just prose", [])


class _ProseThenDone(Client):
    """Writes a write_file call as prose on step 0 (the V1 failure), then speaks."""

    def __init__(self):
        self.n = 0

    def chat(self, messages, tools=None):
        self.n += 1
        if self.n == 1:
            return ChatResult(content=(
                "I'll create the file.<tool_call>write_file<arg_key>path</arg_key>"
                "<arg_value>out.txt</arg_value><arg_key>content</arg_key>"
                "<arg_value>hello</arg_value></tool_call>"))
        return ChatResult(content="done, wrote out.txt. operator, over to you.")


def test_prose_tool_call_is_executed_not_left_as_an_unrun_promise(project):
    calls = []
    ctx = ToolContext(workspace=project.workspace, project=project,
                      on_tool=lambda t, a, o: calls.append((t, a, o)))
    tools = build_tools(["write_file"], ctx)
    line, _ = think_and_act(_ProseThenDone(), system="s", user="u", tools=tools, ctx=ctx)
    # the file the model only *narrated* actually got written
    assert (project.workspace / "out.txt").read_text() == "hello"
    assert line.startswith("done")
    assert calls and calls[0][0] == "write_file"        # and the tool use was recorded


def test_tool_events_land_in_the_order_log(project):
    class _Looker(Client):
        def __init__(self):
            self.n = 0

        def chat(self, messages, tools=None):
            self.n += 1
            if self.n == 1:   # the lead has list_dir; write it as prose
                return ChatResult(content="looking.<tool_call>list_dir<arg_key>path"
                                  "</arg_key><arg_value>.</arg_value></tool_call>")
            return ChatResult(content="operator: had a look, done.")

    order = run_order(project, "research", "look around", echo=False, client=_Looker())
    tool_events = [e for e in order.events if e["kind"] == "tool"]
    assert tool_events
    e = tool_events[0]
    assert e["tool"] == "list_dir" and e["ok"] is True
    assert e["agent"] == "lead" and "args_hash" in e and e["attempt"] == 0
