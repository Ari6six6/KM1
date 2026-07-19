"""The model client — how an agent reaches the LLM.

Three clients behind one small interface. The primary call is ``stream_chat`` —
it yields the model's tokens as they arrive (so the operator watches a mind think
instead of a spinner) and honours a ``Cancel`` token so a turn can be stopped
mid-completion in well under a second without killing the session. ``chat`` is the
same call collected into one result, for callers that don't need the stream
(``mor ping``).

  OpenAIClient  — any OpenAI-compatible ``/chat/completions`` endpoint (vLLM,
                  llama.cpp, Ollama, a hosted API). Stdlib urllib only, Server-Sent
                  Events for the stream, with a short retry ladder so a flaky
                  server never crashes a session. Falls back cleanly if a server
                  ignores ``stream`` and returns one whole body.
  MockClient    — the offline stand-in: a canned, in-character line per agent so
                  the crew still moves with no model attached.
  ScriptClient  — a scripted client for tests, to drive the tool loop.

The last two don't stream token-by-token; they inherit the base ``stream_chat``,
which emits their one line as a single chunk — honest, and enough to keep the
streaming path exercised everywhere.

Small local models sometimes fall into a degenerate repeat loop; ``cut_loops``
trims that at the source before it can poison the transcript everyone reads next.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field

from mor.config import endpoint

_LOOP_MARK = " …(repeat loop trimmed)"
_SENT = re.compile(r"(?<=[.!?…])\s+")


def cut_loops(text: str | None) -> str:
    """Keep a runaway repetition once. Two shapes: the same sentence (24+ chars)
    said three+ times, and the punctuation-free twin — a 12–80 char unit tiling
    the tail. Ordinary text and honest repetition pass through untouched."""
    if not text:
        return text or ""
    counts: dict = {}
    for part in _SENT.split(text):
        norm = " ".join(part.lower().split())
        if len(norm) < 24:
            continue
        counts[norm] = counts.get(norm, 0) + 1
        if counts[norm] == 3:
            first = text.find(part)
            if first >= 0:
                return text[: first + len(part)].rstrip() + _LOOP_MARK
    body = text.rstrip()
    n = len(body)
    for u in range(12, 81):
        if n < 3 * u:
            break
        unit = body[n - u:]
        if body[n - 3 * u:] == unit * 3:
            start = n
            while start - u >= 0 and body[start - u:start] == unit:
                start -= u
            return body[:start + u].rstrip() + _LOOP_MARK
    return text


class Cancel:
    """A one-shot cancel token for a single turn. The REPL sets it on Ctrl-C to
    stop the *completion*, not the session; the streaming reader checks it between
    chunks and returns what it has so far. Thread-safe, so a signal handler on the
    main thread and the reader can share it."""

    def __init__(self):
        self._event = threading.Event()

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON string, as the wire delivers it


@dataclass
class ChatResult:
    content: str | None = None
    tool_calls: list = field(default_factory=list)
    cancelled: bool = False   # True if a Cancel token stopped this completion


class Client:
    def chat(self, messages: list, tools: list | None = None) -> ChatResult:
        raise NotImplementedError

    def stream_chat(self, messages: list, tools: list | None = None, *,
                    on_token=None, cancel: "Cancel | None" = None) -> ChatResult:
        """Default: one shot, no real streaming — emit the whole line as a single
        token. Real streaming lives in OpenAIClient; the offline and scripted
        clients ride this so every caller can speak to one interface."""
        if cancel is not None and cancel.is_set():
            return ChatResult(cancelled=True)
        res = self.chat(messages, tools)
        if on_token and res.content:
            on_token(res.content)
        return res


# --------------------------------------------------------------------------
def _accumulate_tool_calls(store: dict, deltas: list) -> None:
    """Fold a streamed (or whole) list of tool-call fragments into ``store``,
    keyed by index — the wire sends the id and name once and the arguments in
    pieces, so we stitch them back together."""
    for i, tc in enumerate(deltas or []):
        idx = tc.get("index", i)
        slot = store.setdefault(idx, {"id": None, "name": None, "args": ""})
        if tc.get("id"):
            slot["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            slot["name"] = fn["name"]
        if fn.get("arguments"):
            slot["args"] += fn["arguments"]


def _finish(parts: list, tools: dict, cancelled: bool) -> ChatResult:
    text = "".join(parts)
    calls = [ToolCall(s["id"] or f"c{idx}", s["name"] or "", s["args"] or "{}")
             for idx, s in sorted(tools.items())]
    return ChatResult(content=cut_loops(text) if text else None,
                      tool_calls=calls, cancelled=cancelled)


def consume_stream(lines, on_token=None, cancel: "Cancel | None" = None) -> ChatResult:
    """Read an OpenAI-compatible SSE stream into a ChatResult, emitting each text
    delta through ``on_token`` as it lands. Stops early and marks the result
    ``cancelled`` if the token trips mid-stream. Pure over an iterable of lines
    (bytes or str), so it tests without a network."""
    parts: list = []
    tools: dict = {}
    for raw in lines:
        if cancel is not None and cancel.is_set():
            return _finish(parts, tools, cancelled=True)
        line = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw
        line = line.strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        piece = delta.get("content")
        if piece:
            parts.append(piece)
            if on_token:
                on_token(piece)
        if delta.get("tool_calls"):
            _accumulate_tool_calls(tools, delta["tool_calls"])
    return _finish(parts, tools, cancelled=False)


class OpenAIClient(Client):
    RETRY_DELAYS = (1, 3, 8)

    def __init__(self, cfg: dict):
        self.base_url = cfg["base_url"].rstrip("/")
        self.model = cfg.get("model", "local")
        self.api_key = cfg.get("api_key", "-")
        self.temperature = cfg.get("temperature", 0.6)
        self.max_tokens = int(cfg.get("max_tokens", 2048))
        self.timeout = float(cfg.get("timeout", 300))

    def _request(self, body: dict) -> urllib.request.Request:
        return urllib.request.Request(
            f"{self.base_url}/chat/completions", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})

    def _whole(self, payload: dict, on_token) -> ChatResult:
        """Parse one non-streamed body — the fallback for a server that ignores
        ``stream``. Emits the content once so the interface still 'streams'."""
        msg = (payload.get("choices") or [{}])[0].get("message") or {}
        content = msg.get("content")
        if content and on_token:
            on_token(content)
        tools: dict = {}
        _accumulate_tool_calls(tools, msg.get("tool_calls") or [])
        return _finish([content] if content else [], tools, cancelled=False)

    def stream_chat(self, messages: list, tools: list | None = None, *,
                    on_token=None, cancel: "Cancel | None" = None) -> ChatResult:
        body = {"model": self.model, "messages": messages,
                "temperature": self.temperature, "max_tokens": self.max_tokens,
                "stream": True}
        if tools:
            body["tools"] = tools
        last = None
        for delay in (0,) + self.RETRY_DELAYS:
            if cancel is not None and cancel.is_set():
                return ChatResult(cancelled=True)
            if delay:
                time.sleep(delay)
            try:
                with urllib.request.urlopen(self._request(body), timeout=self.timeout) as resp:
                    ctype = resp.headers.get("Content-Type", "")
                    if "text/event-stream" in ctype:
                        return consume_stream(resp, on_token, cancel)
                    payload = json.loads(resp.read().decode("utf-8", "replace"))
                    return self._whole(payload, on_token)
            except Exception as e:  # noqa: BLE001 — a flaky server must not crash a run
                last = e
        return ChatResult(content=f"(the model endpoint didn't respond — "
                                  f"{type(last).__name__}: {str(last)[:120]}). "
                                  "The server or its tunnel may be down: try `mor "
                                  "ping`, and if it's a GPU box, `mor gpu status` "
                                  "then `mor gpu reconnect`.")

    def chat(self, messages: list, tools: list | None = None) -> ChatResult:
        """The stream, collected — for callers that don't render tokens live."""
        return self.stream_chat(messages, tools)


# --------------------------------------------------------------------------
class ScriptClient(Client):
    """A scripted client for tests. Each item is one reply:
    ``{'text': ...}`` or ``{'tool': name, 'args': {...}}`` or
    ``{'tools': [{'tool':.., 'args':..}, ...], 'say': ...}``."""

    def __init__(self, script: list):
        self.script = list(script)
        self._n = 0

    def chat(self, messages: list, tools: list | None = None) -> ChatResult:
        if not self.script:
            return ChatResult(content="(script exhausted)")
        item = self.script.pop(0)
        if "text" in item:
            return ChatResult(content=item["text"])
        calls = item.get("tools") or [{"tool": item["tool"], "args": item.get("args", {})}]
        out = []
        for c in calls:
            self._n += 1
            out.append(ToolCall(f"s{self._n}", c["tool"], json.dumps(c.get("args", {}))))
        return ChatResult(content=item.get("say"), tool_calls=out)


# --------------------------------------------------------------------------
class MockClient(Client):
    """The offline stand-in: one seeded in-character line, no tool calls, so the
    crew visibly moves with no model attached. The orchestrator seeds the line."""

    def __init__(self):
        self._pending = None

    def seed(self, text: str) -> None:
        self._pending = text

    def chat(self, messages: list, tools: list | None = None) -> ChatResult:
        if self._pending is not None:
            text, self._pending = self._pending, None
            return ChatResult(content=text)
        tail = messages[-1]["content"] if messages else ""
        return ChatResult(content=f"(offline: heard '{str(tail)[-80:]}')")


def make_client():
    """OpenAIClient if an endpoint is configured, else the offline MockClient.
    Returns (client, mode) where mode is 'model' or 'offline'."""
    cfg = endpoint()
    if cfg["base_url"]:
        return OpenAIClient(cfg), "model"
    return MockClient(), "offline"
