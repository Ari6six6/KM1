"""The think→act loop — one agent's turn, for real.

Given an agent's system prompt, task, and tools, run the model until it stops
calling tools and produces a plain-text line. Carries two guards worth keeping
from any honest agent loop:

  * the reflect reflex — if it calls tools several times without ever reasoning
    out loud, push it to think before acting again (the guard against a small
    model tool-thrashing past the point);
  * a step budget — it always terminates, and near the end it's told to
    consolidate and answer rather than get cut off mid-reach.

The offline MockClient runs the same loop; it just seeds one line and never
calls a tool, so the machinery stays exercised with no model attached.
"""

from __future__ import annotations

from mor.llm import MockClient
from mor.tools import execute

_REFLECT_AFTER = 2   # act-only steps before we push to think
_MAX_STEPS = 8

_REFLECT_NUDGE = (
    "You have acted several times without reasoning out loud. Stop. In plain "
    "English, say what you have found so far and what it means, then decide your "
    "next move. Do not call another tool until you have thought.")

_BUDGET_NUDGE = (
    "Two steps remain. Stop exploring; consolidate what you have and say your line.")

_EMPTY_NUDGE = (
    "You said nothing. Speak your one plain-English line now — what you see, what "
    "you did, or what you need.")


def think_and_act(client, *, system: str, user: str, tools: list, ctx,
                  seed: str | None = None, log=lambda *_: None,
                  max_steps: int = _MAX_STEPS):
    """Run one agent turn. Returns (spoken_line, tainted)."""
    if isinstance(client, MockClient) and seed is not None:
        client.seed(seed)

    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    openai_tools = [t.openai() for t in tools] if tools else None
    act_streak = 0
    last_text = ""
    warned = False
    empty_nudged = False
    budget = max_steps

    step = 0
    while step < budget:
        if not warned and step == budget - 2 and budget > 2:
            messages.append({"role": "user", "content": _BUDGET_NUDGE})
            warned = True

        res = client.chat(messages, openai_tools)

        if not res.tool_calls:
            if (not (res.content or "").strip() and not empty_nudged
                    and step < budget - 1):
                empty_nudged = True
                messages.append({"role": "user", "content": _EMPTY_NUDGE})
                step += 1
                continue
            line = (res.content or last_text or "(said nothing)").strip()
            return line, bool(ctx.tainted)

        # it's acting — record the assistant turn (with its calls) verbatim
        if res.content:
            last_text = res.content
        messages.append({"role": "assistant", "content": res.content or "",
                         "tool_calls": [{"id": c.id, "type": "function",
                                         "function": {"name": c.name,
                                                      "arguments": c.arguments}}
                                        for c in res.tool_calls]})
        for c in res.tool_calls:
            obs = execute(tools, c, ctx)
            log(f"    · {c.name} → {obs.splitlines()[0][:80] if obs else ''}")
            messages.append({"role": "tool", "tool_call_id": c.id, "content": obs})

        act_streak = act_streak + 1 if not (res.content or "").strip() else 0
        if act_streak >= _REFLECT_AFTER:
            messages.append({"role": "user", "content": _REFLECT_NUDGE})
            act_streak = 0
        step += 1

    messages.append({"role": "user",
                     "content": "Enough acting. Say your line now, in plain English."})
    res = client.chat(messages, None)
    line = (res.content or last_text or "(ran out of steps)").strip()
    return line, bool(ctx.tainted)
