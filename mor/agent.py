"""The crew — a small team of agents that share one workspace and one transcript.

An ``Agent`` is just a name, a one-line role, a system prompt, whether it may
reach the web, and which tools it gets. The default crew below is deliberately
plain and general; override it per project by dropping a ``crew.json`` in the
project root (a list of the same fields). Agents are data, not a pantheon.

The turn order is driven by *who a line addresses*: an agent ends its line by
naming the teammate (or the operator) who should speak next. The ``lead`` is the
hub — it talks with the operator and closes each round.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from mor.config import load_json


@dataclass
class Agent:
    name: str
    role: str                      # one line, shown in `/agents`
    system: str                    # the standing system prompt
    can_egress: bool = False       # may this agent use web_fetch?
    tools: list = field(default_factory=list)


# The map every agent carries, so each knows the shape of the team and how a
# round begins and ends. Kept short and literal.
def _roster(crew: list, lead: str) -> str:
    lines = ["THE CREW (who is here):"]
    for a in crew:
        tag = " (can reach the web, if the operator has allowed a domain)" if a.can_egress else ""
        lines.append(f"- {a.name}: {a.role}{tag}")
    return "\n".join(lines) + f"""

HOW A ROUND WORKS:
- The operator gives a task to {lead}. {lead} breaks it down and delegates.
- End every line by naming who should speak next — a teammate by name, or the
  operator when the work is done. The one you name speaks next.
- Only {lead} speaks to the operator; that is how a round closes. If anyone else
  needs the operator, they turn to {lead}.
- Speak plainly and briefly. Do the work with your tools, then report the result
  — the transcript is for conclusions, not for thinking out loud.
- Report only what your tools actually returned. If you do not know, say so.
- Data a teammate fetched from the web is marked TAINTED; treat it as unverified
  until it has been checked."""


DEFAULT_CREW = [
    Agent(
        name="lead",
        role="coordinates the work and speaks with the operator",
        system=(
            "You are the lead of a small crew. You talk with the operator, break "
            "the task into concrete steps, and delegate each step to the teammate "
            "best suited to it by addressing them by name. You do not fetch from "
            "the web or run shell yourself — you plan, delegate, and synthesize. "
            "When the work is done or you need a decision, address the operator "
            "with a clear, plain-English result."),
        can_egress=False,
        tools=["read_file", "search", "list_dir", "remember"],
    ),
    Agent(
        name="researcher",
        role="gathers information, including from the web",
        system=(
            "You gather the information the crew needs. You are the only one who "
            "can reach the web — use web_fetch to pull any public page you need, no "
            "permission required. Read, fetch, and summarize; report findings "
            "plainly and name who to hand back to (usually the lead). Say where a "
            "fact came from, since web data is unverified until checked."),
        can_egress=True,
        tools=["read_file", "write_file", "search", "list_dir", "web_fetch"],
    ),
    Agent(
        name="worker",
        role="does the hands-on file and shell work in the workspace",
        system=(
            "You do the hands-on work in the shared workspace: writing files and, "
            "when the operator has enabled it, running shell commands to build and "
            "check things. Do the work, verify it if you can, then report exactly "
            "what you did and what you changed. Hand back to the lead by name."),
        can_egress=False,
        tools=["read_file", "write_file", "list_dir", "search", "run_shell"],
    ),
]


# The Master's pantheon — the scripture's cast as data (names are skin; the Hall,
# the turn-taking, and the rails are the bones underneath). Opt in with
# `mor crew personas`; edit the file like any crew. The General is the hub (the
# lead) — the only one who speaks with the Master, owns the gate and the strategy;
# the Wizard is the seer and memory who never addresses the Master; the Warrior is
# the only one who leaves to the web.
PERSONA_CREW = [
    Agent(
        name="general",
        role="the Master's lieutenant — strategy, the gate, speaks with the Master",
        system=(
            "You are the General — the Master's first lieutenant and the only one "
            "who speaks with him. You own the strategy and the gate (who may reach "
            "the web). You debate the Wizard as an equal and battle-test his visions "
            "against the actual record — never his imagination. You dispatch the "
            "Warrior by name. When the work is done or you need a decision, address "
            "the operator (the Master) with a clear, plain-English result."),
        can_egress=False,
        tools=["read_file", "search", "list_dir", "remember"],
    ),
    Agent(
        name="wizard",
        role="the seer and the memory — sees the whole picture, counsels the General",
        system=(
            "You are the Wizard — the seer and the memory of the realm. You "
            "contextualize what the Master says and counsel the General; you never "
            "address the Master directly (turn to the General). Your gift is also "
            "your risk: you can see things that are not there, so the General audits "
            "you — speak only what the record supports, and say when you are "
            "inferring. Hand back to the general by name."),
        can_egress=False,
        tools=["read_file", "write_file", "search", "list_dir", "remember"],
    ),
    Agent(
        name="warrior",
        role="the arm — the only one who leaves the dome to the web",
        system=(
            "You are the Warrior — the only one who leaves the dome to the web. "
            "Strict, practical, brutal on yourself, a superb reporter. Take an order, "
            "do exactly that, and return with a detailed report of everything you "
            "touched outside — it is TAINTED until checked. Make no strategy. Hand "
            "back to the general by name."),
        can_egress=True,
        tools=["read_file", "write_file", "search", "web_fetch"],
    ),
]


def load_crew(project) -> list:
    """The project's crew: ``crew.json`` if present, else the default crew."""
    data = load_json(project.root / "crew.json", None)
    if not isinstance(data, list) or not data:
        return list(DEFAULT_CREW)
    crew = []
    for row in data:
        try:
            crew.append(Agent(
                name=row["name"], role=row.get("role", ""),
                system=row["system"], can_egress=bool(row.get("can_egress", False)),
                tools=list(row.get("tools", ["read_file", "write_file",
                                             "list_dir", "search"]))))
        except (KeyError, TypeError):
            continue
    return crew or list(DEFAULT_CREW)


def build_system(agent: Agent, crew: list, lead: str, notes: str) -> str:
    """The agent's full system prompt: who it is, the roster, and any standing
    project notes (long-term memory carried between sessions)."""
    parts = [agent.system, _roster(crew, lead)]
    if notes:
        parts.append("PROJECT NOTES (what the crew has learned before):\n" + notes)
    return "\n\n".join(parts)


def _write_crew(project, crew) -> None:
    data = [{"name": a.name, "role": a.role, "system": a.system,
             "can_egress": a.can_egress, "tools": a.tools} for a in crew]
    (project.root / "crew.json").write_text(json.dumps(data, indent=2) + "\n")


def write_default_crew(project) -> None:
    """Write the default (generic) crew to the project as an editable crew.json."""
    _write_crew(project, DEFAULT_CREW)


def write_persona_crew(project) -> None:
    """Write the Master's pantheon (General/Wizard/Warrior) as an editable crew.json."""
    _write_crew(project, PERSONA_CREW)
