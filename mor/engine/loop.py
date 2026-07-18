"""The think→act loop — one face's turn, for real.

Given a face (its system voice + task) and its hands (tools), run the model until
it stops acting and says its plain-English line into the Hall. Carries the reflex
cut from Hermes's agent loop: if a face acts several times without ever reasoning
out loud, push it to think before it acts again — the guard against a small mind
tool-thrashing its way past the point.

The offline mind never enters the loop: it speaks one in-character line and stops,
so the realm still moves with no oracle attached.
"""

from __future__ import annotations

import re

from mor.engine.backend import MockBackend, flavored_line
from mor.engine.tools import execute

# How many act-only turns (tool calls, no reasoning) before we push to think.
_REFLECT_AFTER = 2
_MAX_STEPS = 8

_REFLECT_NUDGE = (
    "You have acted several times without reasoning out loud. Stop. In plain "
    "English, say what you have found so far and what it means — then decide your "
    "next move. Do not call another tool until you have thought."
)

_BUDGET_NUDGE = (
    "Two steps remain. Stop exploring; consolidate what you have and say your line."
)

_VERIFY_NUDGE = (
    "You changed files this turn but ran nothing to check them — verification "
    "theater is not the realm's way (the Seventh Evangelism). Run a real check now "
    "(run_shell); and if none is truly possible, say plainly in your spoken line "
    "that the work stands unverified."
)

_EMPTY_NUDGE = (
    "You said nothing. Speak your one plain-English line now — what you see, "
    "what you did, or what you need."
)

# The Eleventh Evangelism — the Audit. A turn that did work must try to BREAK
# its own conclusion before it may speak it: once per turn, aimed at the most
# load-bearing untested belief, and the leash extends to make room for it.
_FALSIFY_NUDGE = (
    "Before you speak. Your turn did work, and the realm does not trust "
    "untested confidence — an answer that was never attacked is a rumor. Name "
    "the ONE assumption your conclusion leans on hardest{claim} and attack it "
    "now: one search or read aimed squarely at proving it WRONG, not "
    "supporting it. Then mark what you attacked in the grimoire (held or "
    "broken — and raise its rung to how you know it now), and only then speak "
    "your line."
)

_FALSIFY_STEPS = 2  # the leash extends by this much to make room for the audit

# The Twelfth Evangelism — the Muzzle. A weak mind loops: it says one sentence,
# likes the sound, and says it eleven more times, and the Hall's tail then
# poisons every turn that reads it. The loop is cut at the source, before the
# record: keep the sentence once, note the cut, move on.
_LOOP_NUDGE = (
    "You have made the exact same tool call three times running — the answer is "
    "already above you. Use it, or change tack entirely; do not ask again."
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _cut_repetition(text: str) -> str:
    """Detect a verbatim loop in a final line and keep it once.

    Two shapes, both deterministic:
      sentence-level — the same sentence (>=25 chars) 3+ times, and
      word-period   — a run of >=8 words that repeats with strict periodicity
                      (the no-punctuation loop small models fall into).
    Returns the text cut at the first loop, with a marker the Hall can see."""
    if not text:
        return text
    # sentence-level
    sentences = [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if len(sentences) >= 3:
        first_seen = {}
        counts = {}
        for idx, s in enumerate(sentences):
            key = " ".join(s.lower().split())
            first_seen.setdefault(key, idx)
            counts[key] = counts.get(key, 0) + 1
            if len(key) >= 25 and counts[key] >= 3:
                kept = " ".join(sentences[:first_seen[key] + 1])
                return kept + " … (the face repeated itself; the Hall kept it once)"
    # word-period
    words = text.split()
    n = len(words)
    for period in range(8, min(120, n // 2) + 1):
        # strict periodicity over at least 3 repetitions starting anywhere
        for start in range(0, min(40, n - 3 * period)):
            chunk = words[start:start + period]
            if not any(len(w) > 3 for w in chunk):
                continue  # loops of filler words are not the sin we're cutting
            reps = 0
            i = start
            while i + period <= n and words[i:i + period] == chunk:
                reps += 1
                i += period
            if reps >= 3:
                kept = " ".join(words[:start + period])
                return kept + " … (the face repeated itself; the Hall kept it once)"
    return text


def think_and_act(backend, *, role: str, kind: str, heard: str, system: str,
                  user: str, tools: list, ctx, log=lambda *_: None,
                  max_steps: int = _MAX_STEPS):
    """Run one face's turn and return (spoken_line, tainted).

    The offline mind doesn't bypass the loop — it seeds an in-character line and
    then runs the *same* loop the served mind does (it just doesn't call tools), so
    the machinery is live and validated even with no GPU attached.
    """
    if isinstance(backend, MockBackend):
        backend.seed(flavored_line(role, kind, heard))

    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    openai_tools = [t.openai() for t in tools] if tools else None
    act_streak = 0
    last_text = ""
    warned = False
    bounced = False
    falsified = False
    acted = False
    empty_nudged = False
    loop_nudged = False
    last_call = None
    call_streak = 0
    budget = max_steps
    # The Seventh: the bounce only exists where a check could actually run —
    # a face with no body cannot execute anything, so it is never asked to.
    can_check = any(t.name == "run_shell" for t in (tools or []))
    # The Eleventh: the audit exists where the face has something to attack
    # with — any way to search or read against its own conclusion.
    can_attack = any(t.name in ("search_workspace", "read_file", "source_search",
                                "source_read", "ask_graph", "recall")
                     for t in (tools or []))

    step = 0
    while step < budget:
        # The budget valve: with two steps left on a long leash, tell the face once
        # to stop exploring and land its answer — so it consolidates rather than
        # getting cut off mid-reach and made to speak cold.
        if not warned and step == budget - 2 and budget > 2:
            messages.append({"role": "user", "content": _BUDGET_NUDGE})
            warned = True

        res = backend.chat(messages, openai_tools)
        if not res.tool_calls:
            # Silence gets one nudge: an empty answer is the oracle stumbling,
            # not the face choosing to say nothing — ask once before accepting it.
            if (not (res.content or "").strip() and not empty_nudged
                    and step < budget - 1):
                empty_nudged = True
                messages.append({"role": "user", "content": _EMPTY_NUDGE})
                step += 1
                continue
            # The Seventh Evangelism: a turn that changed files but ran nothing is
            # bounced ONCE to actually check — or to name the work unverified.
            if (ctx.changed and not ctx.checked and can_check
                    and not bounced and step < budget - 1):
                bounced = True
                messages.append({"role": "user", "content": _VERIFY_NUDGE})
                step += 1
                continue
            # The Eleventh Evangelism: a turn that acted must attack its own
            # conclusion ONCE before speaking it. The leash extends to hold the
            # audit — a falsification squeezed out by the budget is theatre.
            if (getattr(ctx, "falsify", False) and acted and can_attack
                    and not falsified and step < budget - 1):
                falsified = True
                budget += _FALSIFY_STEPS
                claim = ""
                try:
                    from mor import grimoire as _grim
                    best = _grim.next_to_test(ctx.space) if ctx.space else None
                except Exception:  # noqa: BLE001 — a blank book never blocks the audit
                    best = None
                if best is not None:
                    claim = (f' — the grimoire\'s most load-bearing untested '
                             f'claim is "{best["text"]}" ({best["id"]}); attack '
                             f'that one')
                messages.append({"role": "user",
                                 "content": _FALSIFY_NUDGE.format(claim=claim)})
                step += 1
                continue
            # A plain-English answer — this is the face's line in the Hall.
            line = (res.content or last_text or "(said nothing)").strip()
            return _cut_repetition(line), bool(ctx.tainted)

        # It's acting. Record the assistant turn (with its calls) verbatim.
        acted = True
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
            # The Twelfth: the same call three times running is a loop, not a
            # plan — say so once, plainly, instead of watching it spin.
            sig = (c.name, c.arguments or "")
            call_streak = call_streak + 1 if sig == last_call else 1
            last_call = sig
        if call_streak >= 3 and not loop_nudged and step < budget - 1:
            loop_nudged = True
            messages.append({"role": "user", "content": _LOOP_NUDGE})

        # Reflect reflex: acting without thinking gets pushed to think.
        act_streak = act_streak + 1 if not (res.content or "").strip() else 0
        if act_streak >= _REFLECT_AFTER:
            messages.append({"role": "user", "content": _REFLECT_NUDGE})
            act_streak = 0

        step += 1

    # Out of steps: make it say its piece rather than vanish.
    messages.append({"role": "user", "content":
                     "Enough acting. Say your line now, in plain English, for the Hall."})
    res = backend.chat(messages, None)
    line = (res.content or last_text or "(ran out of turns)").strip()
    return _cut_repetition(line), bool(ctx.tainted)
