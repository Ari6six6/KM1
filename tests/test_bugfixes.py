"""Regressions for the BUGREPORT live-fire findings (BUG-01 … BUG-08).

Each test pins the behaviour a bug's fix must keep. They exercise the seams the
report named — the planner client on the live path, honest mode labels, the
reasoning stream, the identical-failure breaker, the outage gate, planner rubrics
for build/fetch, and the token-starvation marker — without a network or a model.
"""

from __future__ import annotations

from mor import fitness
from mor.config import save_json
from mor.llm import (Client, ChatResult, OpenAIClient, MockClient, ScriptClient,
                     ToolCall, consume_stream, split_think)
from mor.loop import think_and_act
from mor.order import run_order
from mor.session import Session, mode_for
from mor.tools import ToolContext, build_tools


def _ctx(project, can_egress=False):
    ws = project.workspace
    ws.mkdir(parents=True, exist_ok=True)
    return ToolContext(workspace=ws, project=project, can_egress=can_egress)


# --- BUG-01 — the planner rubric fires on the live path --------------------
class _ServedPlanner(OpenAIClient):
    """A served model (an OpenAIClient) whose planner authors a real rubric and whose
    crew turns close in one line — no socket."""

    def __init__(self):
        pass

    def chat(self, messages, tools=None):
        return ChatResult(content='{"required_facts": ["canberra"], '
                          '"forbidden_claims": ["sydney"], "require_citation": false}')

    def stream_chat(self, messages, tools=None, *, on_token=None, cancel=None):
        return ChatResult(content="Canberra is the capital. operator: done.")


def test_bug01_execute_order_resolves_a_served_client_so_the_planner_fires(project, monkeypatch):
    # The order used to pass client=None into make_rubric, so the planner seam was
    # dead even with a model served — every live rubric was authored_by "template".
    # execute_order now resolves the mind once; the rubric is authored by the planner.
    monkeypatch.setattr("mor.session.pick_client",
                        lambda project, echo=True: (_ServedPlanner(), "model"))
    order = run_order(project, "research", "what is the capital of australia", echo=False)
    rubric = next(e for e in order.events if e["kind"] == "rubric")
    assert rubric["authored_by"] == "planner"
    assert any(c["type"] == "required_fact" and c["value"] == "canberra"
               for c in rubric["checks"])
    delivered = next(e for e in order.events if e["kind"] == "delivered")
    assert delivered["mode"] == "model"          # and it is labelled a model run


def test_bug01_offline_live_path_is_unchanged_template_and_demo(project):
    # With no model served the resolved client is the offline stand-in: template
    # rubric, DEMO artifact — exactly as before, so a fresh clone still delivers.
    order = run_order(project, "research", "anything at all", echo=False)
    rubric = next(e for e in order.events if e["kind"] == "rubric")
    assert rubric["authored_by"] == "template"
    delivered = next(e for e in order.events if e["kind"] == "delivered")
    assert delivered["mode"] == "offline"
    assert "DEMO" in (order.dir / "report.md").read_text()


# --- BUG-02 — an injected client is labelled by type -----------------------
def test_bug02_injected_served_client_is_a_model_run_not_a_test(project):
    class _Served(OpenAIClient):
        def __init__(self):
            pass

        def stream_chat(self, messages, tools=None, *, on_token=None, cancel=None):
            return ChatResult(content="operator: done.")

    assert Session(project, echo=False, client=_Served()).mode == "model"


def test_bug02_injected_offline_and_scripted_clients_keep_honest_labels(project):
    assert mode_for(MockClient()) == "offline"          # DEMO, not a model run
    assert mode_for(ScriptClient([])) == "test"          # a scripted test client
    assert Session(project, echo=False, client=MockClient()).mode == "offline"


# --- BUG-03 — the reasoning stream is captured, not dropped/leaked ----------
def test_bug03_stream_captures_reasoning_apart_from_the_spoken_content():
    lines = [
        'data: {"choices":[{"delta":{"reasoning_content":"let me think... "}}]}',
        'data: {"choices":[{"delta":{"reasoning_content":"it is 4. "}}]}',
        'data: {"choices":[{"delta":{"content":"The answer is 4."}}]}',
        "data: [DONE]",
    ]
    toks = []
    res = consume_stream(lines, on_token=toks.append)
    assert res.content == "The answer is 4."
    assert res.reasoning and "it is 4" in res.reasoning
    assert toks == ["The answer is 4."]           # reasoning never reaches on_token


def test_bug03_inline_think_is_lifted_out_of_content():
    clean, reasoning = split_think("<think>weigh the fords</think>Route north.")
    assert clean == "Route north." and reasoning == "weigh the fords"
    # an unclosed <think> (the stream ran out) is all reasoning, no spoken line
    clean2, reasoning2 = split_think("<think>still weighing and out of budget")
    assert clean2 == "" and "still weighing" in reasoning2


def test_bug03_whole_body_fallback_reads_reasoning():
    client = OpenAIClient({"base_url": "http://x/v1", "model": "m"})
    res = client._whole({"choices": [{"message": {
        "content": "hi", "reasoning_content": "thought about it"}}]}, None)
    assert res.content == "hi" and res.reasoning == "thought about it"


def test_bug03_loop_emits_reasoning_to_the_sink(project):
    ctx = _ctx(project)
    seen = []
    ctx.on_reasoning = seen.append

    class _Reasoner(Client):
        def chat(self, messages, tools=None):
            return ChatResult(content="Done.", reasoning="I reasoned it through.")

    line, _ = think_and_act(_Reasoner(), system="s", user="u", tools=[], ctx=ctx)
    assert line == "Done."
    assert seen == ["I reasoned it through."]


def test_bug03_order_records_reasoning_events(project):
    class _Reasoner(Client):
        def chat(self, messages, tools=None):
            return ChatResult(content="operator: the ford is out.",
                              reasoning="checked the map and the water level")

    order = run_order(project, "research", "is the ford out?", echo=False, client=_Reasoner())
    rev = [e for e in order.events if e["kind"] == "reasoning"]
    assert rev and rev[0]["agent"] and rev[0]["chars"] > 0
    assert "checked the map" in rev[0]["text"]


# --- BUG-04 — the identical-failure circuit breaker ------------------------
def test_bug04_second_identical_failure_is_denied_hard(project):
    ctx = _ctx(project)
    saw_breaker = {"v": False}

    class _Thrash(Client):
        def chat(self, messages, tools=None):
            for m in messages:
                if m.get("role") == "tool" and "already failed" in (m.get("content") or ""):
                    saw_breaker["v"] = True
                    return ChatResult(content="fine, I'll change approach. operator: done.")
            # the same doomed call, over and over, with no adaptation
            return ChatResult(content=None, tool_calls=[
                ToolCall("c", "read_file", '{"path": "nope.txt"}')])

    think_and_act(_Thrash(), system="s", user="u",
                  tools=build_tools(["read_file"], ctx), ctx=ctx, max_steps=8)
    assert saw_breaker["v"], "the identical-failure breaker never fired"


# --- BUG-05 — an outage notice is not a report -----------------------------
def test_bug05_is_outage_detects_the_documented_signatures():
    assert fitness.is_outage("(the model endpoint didn't respond — TimeoutError)")
    assert fitness.is_outage("the endpoint did not answer this time")
    assert not fitness.is_outage("here is a real, sourced answer about endpoints")


def test_bug05_outage_report_scores_zero_and_names_itself():
    outage = "(the model endpoint didn't respond — TimeoutError). The server may be down."
    rubric = {"checks": [{"type": "nonempty_report", "value": ""}]}
    fit = fitness.score("research", "x", outage, None, rubric)
    assert fit["scalar"] == 0.0 and "endpoint_up" in fit["failing"]


def test_bug05_order_refuses_to_deliver_an_outage_string(project):
    class _Down(Client):
        def chat(self, messages, tools=None):
            return ChatResult(content="(the model endpoint didn't respond — "
                              "TimeoutError). operator: done.")

    order = run_order(project, "research", "anything", echo=False, client=_Down())
    assert order.state == "failed"
    failed = next(e for e in order.events if e["kind"] == "failed")
    assert "endpoint" in failed["reason"].lower()


# --- BUG-06 — build rubric is planner-authored, not empty ------------------
def test_bug06_planner_authors_a_build_acceptance_test(project):
    class _Planner(OpenAIClient):
        def __init__(self):
            pass

        def chat(self, messages, tools=None):
            return ChatResult(content="from solution import add\n"
                              "assert add(2, 3) == 5\nprint('ok')\n")

    r = fitness.make_rubric("build", "add(a,b) in solution.py",
                            client=_Planner(), workspace=project.workspace)
    assert r["authored_by"] == "planner"
    acc = [c for c in r["checks"] if c["type"] == "acceptance_test"]
    assert acc and "assert add(2, 3) == 5" in acc[0]["content"]


def test_bug06_build_without_a_test_or_a_model_stays_advisory(project):
    # offline / no served planner → empty checks (advisory), exactly as before
    r = fitness.make_rubric("build", "a thing", workspace=project.workspace)
    assert r["authored_by"] == "template" and r["checks"] == []


def test_bug06_build_cannot_deliver_1_0_with_an_empty_workspace(project):
    # armed build gate + a planner-frozen exam = a build with no code fails, instead
    # of degrading to nonempty=1.0 on an empty tree.
    save_json(project.root / "realm" / "calibration.json",
              {"build": {"gate": "armed", "theta": 0.5, "D": 1.0}})

    class _Crew(OpenAIClient):
        def __init__(self):
            pass

        def chat(self, messages, tools=None):     # the planner authors the exam
            return ChatResult(content="from solution import add\n"
                              "assert add(2, 3) == 5\nprint('ok')\n")

        def stream_chat(self, messages, tools=None, *, on_token=None, cancel=None):
            return ChatResult(content="operator: I built nothing.")

    order = run_order(project, "build", "add(a,b) in solution.py",
                      echo=False, client=_Crew())
    assert order.state == "failed"
    rubric = next(e for e in order.events if e["kind"] == "rubric")
    assert rubric["authored_by"] == "planner"


# --- BUG-07 — fetch rubric checks the workspace, not just nonempty ---------
def test_bug07_planner_authors_fetch_specs(project):
    class _Planner(OpenAIClient):
        def __init__(self):
            pass

        def chat(self, messages, tools=None):
            return ChatResult(content='{"expected_files": ["data.json"], '
                              '"required_facts": ["population"], "require_citation": true}')

    r = fitness.make_rubric("fetch", "grab the population figures", client=_Planner())
    assert r["authored_by"] == "planner"
    types = {c["type"] for c in r["checks"]}
    assert {"files_present", "required_fact", "citation"} <= types


def test_bug07_fetch_without_a_model_is_the_nonempty_template(project):
    r = fitness.make_rubric("fetch", "x")
    assert r["authored_by"] == "template"
    assert r["checks"] == [{"type": "nonempty_report", "value": ""}]


def test_bug07_files_present_leg_discriminates_a_real_fetch(project):
    rubric = {"checks": [{"type": "files_present", "value": "data.json"}]}
    ws = project.workspace
    ws.mkdir(parents=True, exist_ok=True)
    assert fitness.score("fetch", "x", "a report body", ws, rubric)["scalar"] < 1.0
    (ws / "data.json").write_text("{}")
    assert fitness.score("fetch", "x", "a report body", ws, rubric)["scalar"] == 1.0


# --- BUG-08 — token starvation is named, not passed off as silence ---------
def test_bug08_starved_reasoning_yields_a_marker_not_a_blank_line(project):
    ctx = _ctx(project)

    class _Starved(Client):
        def chat(self, messages, tools=None):
            return ChatResult(content=None,
                              reasoning="a very long thought that ate the whole budget")

    line, _ = think_and_act(_Starved(), system="s", user="u", tools=[], ctx=ctx, max_steps=4)
    assert "raise max_tokens" in line


def test_bug08_genuine_silence_is_not_mistaken_for_starvation(project):
    ctx = _ctx(project)

    class _Silent(Client):
        def chat(self, messages, tools=None):
            return ChatResult(content="")     # nothing said, and nothing thought

    line, _ = think_and_act(_Silent(), system="s", user="u", tools=[], ctx=ctx, max_steps=4)
    assert "raise max_tokens" not in line
