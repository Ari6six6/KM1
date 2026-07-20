"""The Gate — the scalar that closes the loop: scoring, the armed/advisory verdict,
and keep-best driving a real verifying→executing cycle."""

from __future__ import annotations

from mor import fitness
from mor.config import save_json
from mor.llm import Client, ChatResult
from mor.order import run_order, OrderStore


def test_rubric_rides_the_log_not_the_hall():
    r = fitness.make_rubric("research", "top async http libraries, cite a source")
    assert r["authored_by"] == "template"
    types = {c["type"] for c in r["checks"]}
    assert "required_fact" in types and "citation_substring" in types


def test_score_separates_a_clean_report_from_poison():
    rubric = {"checks": [
        {"type": "required_fact", "value": "httpx"},
        {"type": "required_fact", "value": "aiohttp"},
        {"type": "citation_substring", "value": "http"},
        {"type": "forbidden_claim", "value": "requests supports async"}]}
    clean = "httpx and aiohttp are async. Source: https://python-httpx.org"
    poison = "requests supports async natively. no link."
    good = fitness.score("research", "", clean, None, rubric)
    bad = fitness.score("research", "", poison, None, rubric)
    assert good["scalar"] > bad["scalar"]
    assert good["scalar"] >= 0.999 and not good["failing"]
    # the poison trips the forbidden gate and the missing citation — named for the retry
    assert "forbidden_absent" in bad["failing"] and "citations" in bad["failing"]
    assert bad["critique"]


def test_gate_is_advisory_without_a_calibration(project):
    verdict, theta = fitness.gate(0.4, "research", project)
    assert verdict == "advisory" and theta is None


def test_gate_blocks_below_theta_once_armed(project):
    save_json(project.root / "realm" / "calibration.json",
              {"research": {"gate": "armed", "theta": 0.8, "D": 1.0}})
    assert fitness.gate(0.95, "research", project) == ("accept", 0.8)
    assert fitness.gate(0.50, "research", project) == ("reject", 0.8)


class _BadThenGood(Client):
    """A crew that answers poorly, then — coached by the critique — answers well.
    Proves the loop retries on a licensed shortfall and keeps the better attempt."""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None):
        # the coached retry is visible in the task text of the last user turn
        coached = any("scored and fell short" in m.get("content", "")
                      for m in messages if m.get("role") == "user")
        self.calls += 1
        if coached:
            return ChatResult(content="httpx and aiohttp do async; requests is sync. "
                                      "Source: https://python-httpx.org . operator: done.")
        return ChatResult(content="here is a vague answer with no specifics. operator: done.")


def test_armed_gate_retries_and_keeps_the_better_attempt(project):
    # arm the research gate with a threshold only a sourced, specific answer clears
    save_json(project.root / "realm" / "calibration.json",
              {"research": {"gate": "armed", "theta": 0.75, "D": 1.0}})
    # brief avoids the string "http" so the citation check actually discriminates
    # (the rendered report echoes the brief, so brief-derived facts are trivially met)
    order = run_order(project, "research",
                      "which python libraries do async, and cite your source",
                      echo=False, client=_BadThenGood())
    kinds = [e["kind"] for e in order.events]
    assert "retry" in kinds                       # the loop bounced the first attempt
    assert order.state == "delivered"             # the coached retry cleared the bar
    scored = [e["scalar"] for e in order.events if e["kind"] == "fitness"]
    assert len(scored) >= 2 and scored[-1] > scored[0]
    delivered = next(e for e in order.events if e["kind"] == "delivered")
    assert delivered["gate"] == "armed" and delivered["chosen_attempt"] >= 1


def test_armed_gate_fails_with_a_reason_not_a_graveyard(project):
    save_json(project.root / "realm" / "calibration.json",
              {"research": {"gate": "armed", "theta": 0.99, "D": 1.0}})

    class _AlwaysVague(Client):
        def chat(self, messages, tools=None):
            return ChatResult(content="a vague non-answer. operator: done.")

    order = run_order(project, "research", "a hard one, cite it", echo=False,
                      client=_AlwaysVague())
    assert order.state == "failed"
    failed = next(e for e in order.events if e["kind"] == "failed")
    assert "best_score" in failed and "critique" in failed and failed["best_attempt"] == 0
    # keep-best still left the best artifact on disk (a stop with a reason)
    assert (order.dir / "report.md").exists()
    assert OrderStore(project).load(order.id).state == "failed"
