"""The model client — how an agent reaches the LLM.

Three clients behind one tiny interface (``chat(messages, tools) -> ChatResult``):

  OpenAIClient  — any OpenAI-compatible ``/chat/completions`` endpoint (vLLM,
                  llama.cpp, Ollama, a hosted API). Stdlib urllib only, with a
                  short retry ladder so a flaky server never crashes a session.
  MockClient    — the offline stand-in: a canned, in-character line per agent so
                  the crew still moves with no model attached.
  ScriptClient  — a scripted client for tests, to drive the tool loop.

Small local models sometimes fall into a degenerate repeat loop; ``cut_loops``
trims that at the source before it can poison the transcript everyone reads next.
"""

from __future__ import annotations

import json
import re
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


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON string, as the wire delivers it


@dataclass
class ChatResult:
    content: str | None = None
    tool_calls: list = field(default_factory=list)


class Client:
    def chat(self, messages: list, tools: list | None = None) -> ChatResult:
        raise NotImplementedError


# --------------------------------------------------------------------------
class OpenAIClient(Client):
    RETRY_DELAYS = (1, 3, 8)

    def __init__(self, cfg: dict):
        self.base_url = cfg["base_url"].rstrip("/")
        self.model = cfg.get("model", "local")
        self.api_key = cfg.get("api_key", "-")
        self.temperature = cfg.get("temperature", 0.6)
        self.max_tokens = int(cfg.get("max_tokens", 2048))
        self.timeout = float(cfg.get("timeout", 300))

    def _post(self, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=data,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def chat(self, messages: list, tools: list | None = None) -> ChatResult:
        body = {"model": self.model, "messages": messages,
                "temperature": self.temperature, "max_tokens": self.max_tokens}
        if tools:
            body["tools"] = tools
        last = None
        for delay in (0,) + self.RETRY_DELAYS:
            if delay:
                time.sleep(delay)
            try:
                payload = self._post(body)
                msg = payload["choices"][0]["message"]
                calls = [ToolCall(tc.get("id", f"c{i}"),
                                  tc["function"]["name"],
                                  tc["function"].get("arguments") or "{}")
                         for i, tc in enumerate(msg.get("tool_calls") or [])]
                return ChatResult(content=cut_loops(msg.get("content")),
                                  tool_calls=calls)
            except Exception as e:  # noqa: BLE001 — a flaky server must not crash a run
                last = e
        return ChatResult(content=f"(the model did not answer — "
                                  f"{type(last).__name__}: {str(last)[:120]}. "
                                  "Check `mor config`.)")


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
