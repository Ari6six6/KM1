"""The streaming, cancellable mind — SSE parsing, cancellation, and loop wiring.

These exercise the interface without a network: ``consume_stream`` is pure over an
iterable of SSE lines, and the offline/scripted clients ride the base
``stream_chat``. The one place that talks to a socket (OpenAIClient.stream_chat)
is left to integration; its whole-body fallback parser is unit-tested directly.
"""

from __future__ import annotations

from mor.llm import (Cancel, Client, ChatResult, OpenAIClient, ScriptClient,
                     consume_stream)
from mor.loop import think_and_act
from mor.tools import ToolContext, build_tools


def _ctx(project):
    ws = project.workspace
    ws.mkdir(parents=True, exist_ok=True)
    return ToolContext(workspace=ws, project=project)


# --- consume_stream: the SSE reader ----------------------------------------
def test_stream_assembles_content_and_emits_each_token():
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo, "}}]}',
        'data: {"choices":[{"delta":{"content":"world."}}]}',
        "data: [DONE]",
    ]
    toks = []
    res = consume_stream(lines, on_token=toks.append)
    assert res.content == "Hello, world."
    assert toks == ["Hel", "lo, ", "world."]   # streamed piece by piece
    assert res.cancelled is False


def test_stream_stitches_a_tool_call_split_across_chunks():
    lines = [
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
        '"function":{"name":"read_file","arguments":"{\\"pa"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"th\\": \\"f\\"}"}}]}}]}',
        "data: [DONE]",
    ]
    res = consume_stream(lines)
    assert len(res.tool_calls) == 1
    call = res.tool_calls[0]
    assert call.id == "call_1" and call.name == "read_file"
    assert call.arguments == '{"path": "f"}'


def test_stream_ignores_keepalives_and_garbage():
    lines = [": keep-alive", "", 'data: not json', 'data: {"choices":[{"delta":{"content":"ok"}}]}',
             "data: [DONE]"]
    res = consume_stream(lines)
    assert res.content == "ok"


def test_stream_honors_cancel_and_returns_partial():
    lines = [
        'data: {"choices":[{"delta":{"content":"first"}}]}',
        'data: {"choices":[{"delta":{"content":"-second"}}]}',
        "data: [DONE]",
    ]
    cancel = Cancel()
    toks = []

    def on_tok(t):
        toks.append(t)
        cancel.set()          # trip the token after the very first piece

    res = consume_stream(lines, on_token=on_tok, cancel=cancel)
    assert res.cancelled is True
    assert res.content == "first"      # only what arrived before the cancel
    assert toks == ["first"]


# --- OpenAIClient whole-body fallback (server ignored stream=True) ----------
def test_whole_body_fallback_parses_content_and_tools():
    client = OpenAIClient({"base_url": "http://x/v1", "model": "m"})
    toks = []
    res = client._whole({"choices": [{"message": {"content": "pong"}}]}, toks.append)
    assert res.content == "pong" and toks == ["pong"]

    res2 = client._whole({"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "a", "function": {"name": "read_file", "arguments": "{}"}}]}}]}, None)
    assert res2.tool_calls[0].name == "read_file"


# --- the base stream_chat: offline / scripted clients ride it --------------
def test_base_stream_chat_emits_the_whole_line_once():
    class One(Client):
        def chat(self, messages, tools=None):
            return ChatResult(content="one shot")

    toks = []
    res = One().stream_chat([], on_token=toks.append)
    assert toks == ["one shot"] and res.content == "one shot"


def test_base_stream_chat_short_circuits_a_preset_cancel():
    class Boom(Client):
        def chat(self, messages, tools=None):
            raise AssertionError("must not be called once cancelled")

    cancel = Cancel()
    cancel.set()
    res = Boom().stream_chat([], cancel=cancel)
    assert res.cancelled is True


# --- the loop honours streaming and cancellation ---------------------------
def test_loop_streams_tokens_through_on_token(project):
    ctx = _ctx(project)
    toks = []
    line, _ = think_and_act(
        ScriptClient([{"text": "The east ford is out; route north."}]),
        system="s", user="u", tools=build_tools(["read_file"], ctx), ctx=ctx,
        on_token=toks.append)
    assert line == "The east ford is out; route north."
    assert "".join(toks) == "The east ford is out; route north."


def test_loop_stops_immediately_when_cancelled(project):
    ctx = _ctx(project)

    class Forever(Client):
        def chat(self, messages, tools=None):
            raise AssertionError("cancel should stop the loop before any call")

    cancel = Cancel()
    cancel.set()
    line, _ = think_and_act(Forever(), system="s", user="u",
                            tools=build_tools(["read_file"], ctx), ctx=ctx,
                            cancel=cancel)
    assert line  # a clean line, no exception, no model call


# --- OpenAIClient over a faked socket (the real streaming path) ------------
class _FakeResp:
    def __init__(self, lines, ctype="text/event-stream"):
        self._lines = lines
        self.headers = {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._lines)

    def read(self):
        return b"".join(self._lines)


def test_openai_streams_over_a_fake_socket(monkeypatch):
    lines = [b'data: {"choices":[{"delta":{"content":"po"}}]}\n',
             b'data: {"choices":[{"delta":{"content":"ng"}}]}\n',
             b"data: [DONE]\n"]
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _FakeResp(lines))
    client = OpenAIClient({"base_url": "http://x/v1", "model": "m"})
    toks = []
    res = client.stream_chat([{"role": "user", "content": "ping"}], on_token=toks.append)
    assert res.content == "pong" and toks == ["po", "ng"]


def test_openai_stream_cancels_mid_socket(monkeypatch):
    lines = [b'data: {"choices":[{"delta":{"content":"one"}}]}\n',
             b'data: {"choices":[{"delta":{"content":"-two"}}]}\n',
             b"data: [DONE]\n"]
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _FakeResp(lines))
    client = OpenAIClient({"base_url": "http://x/v1"})
    cancel = Cancel()
    res = client.stream_chat([], on_token=lambda t: cancel.set(), cancel=cancel)
    assert res.cancelled is True and res.content == "one"


def test_openai_falls_back_to_whole_body(monkeypatch):
    import json
    body = [json.dumps({"choices": [{"message": {"content": "whole"}}]}).encode()]
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _FakeResp(body, ctype="application/json"))
    client = OpenAIClient({"base_url": "http://x/v1"})
    res = client.stream_chat([])
    assert res.content == "whole" and res.cancelled is False
